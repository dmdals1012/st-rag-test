import streamlit as st
import requests
import json
import re
import time
from datetime import datetime, timedelta
import boto3
import pandas as pd


API_URL = "http://54.180.25.122:80/api/v1/chat/message"
CHATROOM_ID = "d34fd4c4-e4d6-43c9-bb6f-964401085b7e"


def linkify_news_numbers(answer, references):
    def replace_func(match):
        num = int(match.group(1))
        if references and 1 <= num <= len(references):
            link = references[num - 1].get("link", "")
            if link:
                return f"[{num}]({link})"
        return match.group(0)
    return re.sub(r"\b(\d+)\b", replace_func, answer)


def inject_custom_css():
    st.markdown(
        """
    <style>
    body, .stApp { background-color: #f8f8fa; font-family: 'Segoe UI', sans-serif; }
    h1 { color: #8B0000; border-bottom: 2px solid #8B0000; }
    .debug-log { background-color: #f8f9fa; font-family: 'Consolas', monospace; font-size: 13px; max-height: 600px; white-space: pre-wrap; overflow-y: auto; border-radius: 8px; padding: 12px; border: 1px solid #e2e8f0;}
    </style>
    """,
        unsafe_allow_html=True,
    )

# ------------------------------------------------------------------------
# 최신 스트림 한 개만 지정해서 그 안의 로그만 가져오는 방식 적용
# ------------------------------------------------------------------------

class DebugLogger:
    def __init__(self):
        self._ensure_session_state()
        self.setup_cloudwatch_client()

    def _ensure_session_state(self):
        if "debug_logs" not in st.session_state:
            st.session_state.debug_logs = []
        if "cloudwatch_logs" not in st.session_state:
            st.session_state.cloudwatch_logs = []
        if "current_prompt" not in st.session_state:
            st.session_state.current_prompt = None
        if "cloudwatch_stream_name" not in st.session_state:
            st.session_state.cloudwatch_stream_name = None

    def add_log(self, log_type, message, data=None):
        self._ensure_session_state()
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = {"timestamp": timestamp, "type": log_type, "message": message, "data": data}
        st.session_state.debug_logs.append(log_entry)
        if len(st.session_state.debug_logs) > 1000:
            st.session_state.debug_logs = st.session_state.debug_logs[-1000:]

    def save_prompt(self, prompt_text):
        self._ensure_session_state()
        st.session_state.current_prompt = prompt_text

    def setup_cloudwatch_client(self):
        try:
            aws_access_key_id = st.secrets["aws_access_key_id"]
            aws_secret_access_key = st.secrets["aws_secret_access_key"]
            region_name = st.secrets.get("region_name", "ap-northeast-2")
            self.cloudwatch_client = boto3.client(
                "logs",
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=region_name,
            )
        except Exception as e:
            self.cloudwatch_client = None
            self.add_log("ERROR", f"CloudWatch client setup failed: {e}")

    def get_latest_log_stream_name(self, log_group_name):
        """CloudWatch에서 최신 로그 스트림 이름을 반환"""
        try:
            resp = self.cloudwatch_client.describe_log_streams(
                logGroupName=log_group_name,
                orderBy="LastEventTime",
                descending=True,
                limit=1
            )
            streams = resp.get("logStreams", [])
            if not streams:
                return None
            return streams[0]["logStreamName"]
        except Exception as e:
            self.add_log("ERROR", f"CloudWatch stream 조회 실패: {e}")
            return None

    def fetch_logs_from_latest_stream(self, log_group_name, limit=50):
        """최신 로그 스트림에서만 이벤트를 가져온다."""
        if not self.cloudwatch_client:
            self.add_log("ERROR", "CloudWatch client not initialized")
            return []
        stream_name = self.get_latest_log_stream_name(log_group_name)
        if not stream_name:
            self.add_log("ERROR", "최신 로그 스트림이 없습니다")
            return []
        st.session_state.cloudwatch_stream_name = stream_name
        try:
            response = self.cloudwatch_client.filter_log_events(
                logGroupName=log_group_name,
                logStreamNames=[stream_name],
                limit=limit,
                interleaved=True
            )
            events = response.get('events', [])
            logs = []
            for event in events:
                ts = datetime.utcfromtimestamp(event['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                msg = event.get('message', '')
                logs.append({"timestamp": ts, "message": msg})
            return logs
        except Exception as e:
            self.add_log("ERROR", f"CloudWatch 이벤트 조회 실패: {e}")
            return []

# ------------------------------------------------------------------------

def render_log_download_button(logs, label="로그 다운로드", key="download_logs"):
    full_log_text = ""
    for log in logs:
        timestamp = log.get("timestamp", "")
        level_or_type = log.get("level") or log.get("type") or ""
        message = log.get("message", "")
        full_log_text += f"[{timestamp}] {level_or_type}: {message}\n"
        extra = log.get("extra_data") or log.get("data")
        if extra:
            extra_str = str(extra)
            preview = extra_str[:500] + "..." if len(extra_str) > 500 else extra_str
            full_log_text += f"  └─ {preview}\n"
    st.download_button(
        label=label,
        data=full_log_text,
        file_name=f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        mime="text/plain",
        key=key,
    )


def render_debug_sidebar(debug_logger):
    st.sidebar.markdown("## 🐛 디버그 모드")
    col1, col2, col3 = st.sidebar.columns([1, 1, 1])
    with col1:
        if st.button("🔄 새로고침", key="refresh_logs"):
            st.rerun()
    with col2:
        if st.button("🗑️ 로그 클리어", key="clear_logs"):
            st.session_state.debug_logs = []
            st.session_state.cloudwatch_logs = []
            st.session_state.current_prompt = None
            st.rerun()
    with col3:
        log_count = st.selectbox("표시 개수", [20, 50, 100, 200, "전체"], index=1, key="log_display_count")

    tab1, tab2, tab3 = st.sidebar.tabs(["시스템 로그", "CloudWatch", "프롬프트"])

    with tab1:
        st.markdown("### 📋 시스템 로그")
        if hasattr(st.session_state, "debug_logs") and st.session_state.debug_logs:
            display_logs = (
                st.session_state.debug_logs
                if log_count == "전체"
                else st.session_state.debug_logs[-int(log_count) :]
            )
            log_text = ""
            for log in reversed(display_logs):
                log_text += f"[{log['timestamp']}] {log['type']}: {log['message']}\n"
                if log.get("data"):
                    data_str = str(log["data"])
                    if len(data_str) > 500:
                        log_text += f"  └─ Data: {data_str[:500]}... (총 {len(data_str)}자)\n"
                    else:
                        log_text += f"  └─ Data: {data_str}\n"
                log_text += "\n"
            st.markdown(f'<div class="debug-log">{log_text}</div>', unsafe_allow_html=True)
            st.caption(f"전체 {len(st.session_state.debug_logs)}개 중 {len(display_logs)}개 표시")
            render_log_download_button(display_logs, label="시스템 로그 다운로드", key="download_system_logs")
        else:
            st.info("아직 로그가 없습니다.")

    with tab2:
        st.markdown("### ☁️ CloudWatch (최신 로그 스트림 로그)")
        # 최신 스트림에 대해 로그 새로고침
        if st.button("로그 새로고침", key="refresh_cw_logs"):
            logs = debug_logger.fetch_logs_from_latest_stream(
                log_group_name="/aws/lambda/vector-search-api",
                limit=100
            )
            st.session_state.cloudwatch_logs = logs
            st.rerun()

        latest_stream = st.session_state.get("cloudwatch_stream_name","-")
        st.markdown(f"<span style='font-size:12px;'>최근 이벤트 스트림: <b>{latest_stream}</b></span>", unsafe_allow_html=True)

        if hasattr(st.session_state, "cloudwatch_logs") and st.session_state.cloudwatch_logs:
            display_cw_logs = (
                st.session_state.cloudwatch_logs
                if log_count == "전체"
                else st.session_state.cloudwatch_logs[-int(log_count) :]
            )
            df = pd.DataFrame(display_cw_logs)
            st.table(df)
            render_log_download_button(
                display_cw_logs, label="CloudWatch 로그 다운로드", key="download_cw_logs"
            )
        else:
            st.info("CloudWatch 로그가 없습니다.")

    with tab3:
        st.markdown("### 📝 프롬프트 내용")
        if hasattr(st.session_state, "current_prompt") and st.session_state.current_prompt:
            prompt_text = st.session_state.current_prompt
            st.markdown(f'<div class="debug-log">{prompt_text}</div>', unsafe_allow_html=True)
            st.caption(f"프롬프트 길이: {len(prompt_text)} 글자")
            if st.button("📥 프롬프트 다운로드", key="download_prompt"):
                st.download_button(
                    label="프롬프트 다운로드",
                    data=prompt_text,
                    file_name=f"prompt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    mime="text/plain",
                )
        else:
            st.info("아직 프롬프트가 수신되지 않았습니다.")


def main():
    inject_custom_css()
    if "debug_logger" not in st.session_state:
        st.session_state.debug_logger = DebugLogger()
    debug_logger = st.session_state.debug_logger

    debug_mode = st.checkbox("🐛 디버그 모드 활성화", key="debug_mode")

    if debug_mode:
        render_debug_sidebar(debug_logger)

    st.title("📰 조선일보 AI POC 시연")

    question = st.text_input("🔍 검색어 입력", "", key="unique_question_input")

    if st.button("검색", key="unique_search_button") and question.strip():
        debug_logger.add_log("USER_INPUT", f"검색 쿼리 입력: {question}")

        if debug_mode:
            debug_logger.add_log("DEBUG_MODE", "디버그 모드에서 검색 실행")

        payload = {"chatRoomsId": CHATROOM_ID, "question": question}

        debug_logger.add_log("API_REQUEST", "API 요청 준비 완료", payload)

        answer_placeholder = st.empty()
        time_placeholder = st.empty()

        full_answer_pure = ""
        answer_with_links = ""
        references = None
        keywords = None
        prompt = None

        start_time = time.time()
        first_token_time = None
        total_elapsed = None

        try:
            with st.spinner("검색 중..."):
                resp = requests.post(API_URL, json=payload, stream=True, timeout=60)
                resp.raise_for_status()

                for line_bytes in resp.iter_lines(decode_unicode=True):
                    if not line_bytes:
                        continue

                    if first_token_time is None:
                        first_token_time = time.time()

                    if line_bytes.strip() == "[done]":
                        break

                    if line_bytes.startswith("data:"):
                        json_str = line_bytes[len("data:") :].strip()
                    else:
                        json_str = line_bytes.strip()
                    if not json_str:
                        continue

                    try:
                        data = json.loads(json_str)
                        if debug_mode:
                            debug_logger.add_log(
                                "STREAM_DATA", "JSON 데이터 파싱 성공", list(data.keys())
                            )
                    except json.JSONDecodeError as e:
                        if debug_mode:
                            debug_logger.add_log(
                                "ERROR", f"JSON 파싱 실패: {str(e)}", json_str[:100]
                            )
                        continue

                    prompt_data = data.get("prompt")
                    if prompt is None and prompt_data:
                        if debug_mode:
                            debug_logger.add_log(
                                "PROMPT", f"프롬프트 데이터 수신: {len(str(prompt_data))}자"
                            )

                        if (
                            isinstance(prompt_data, str)
                            and prompt_data.strip()
                            and prompt_data != "undefined"
                        ):
                            prompt = prompt_data
                            if debug_mode:
                                debug_logger.save_prompt(prompt)
                                debug_logger.add_log(
                                    "PROMPT",
                                    "프롬프트 내용 저장 완료",
                                    {
                                        "length": len(prompt),
                                        "preview": prompt[:100] + "..."
                                        if len(prompt) > 100
                                        else prompt,
                                    },
                                )
                        else:
                            if debug_mode:
                                debug_logger.add_log(
                                    "PROMPT", "유효하지 않은 프롬프트 데이터", prompt_data
                                )

                    if keywords is None and data.get("keywords"):
                        keywords = data["keywords"]
                        if debug_mode:
                            debug_logger.add_log("KEYWORDS", f"키워드 수신: {keywords}")

                    answer_part = data.get("answer")
                    if answer_part:
                        full_answer_pure += answer_part
                        if references:
                            answer_with_links = linkify_news_numbers(full_answer_pure, references)
                            answer_placeholder.markdown(answer_with_links, unsafe_allow_html=True)
                        else:
                            answer_placeholder.markdown(full_answer_pure)

                    if references is None and data.get("references"):
                        references = data["references"]
                        if debug_mode:
                            debug_logger.add_log(
                                "REFERENCES", f"참조 뉴스 수신: {len(references)}개"
                            )

                        answer_with_links = linkify_news_numbers(full_answer_pure, references)
                        answer_placeholder.markdown(answer_with_links, unsafe_allow_html=True)

                total_elapsed = time.time() - start_time
                if first_token_time:
                    first_latency = first_token_time - start_time
                    time_placeholder.success(
                        f"✅ 응답 시작까지: {first_latency:.2f}초 / 전체 소요 시간: {total_elapsed:.2f}초"
                    )
                else:
                    time_placeholder.success(f"✅ 전체 소요 시간: {total_elapsed:.2f}초")

                if debug_mode:
                    debug_logger.add_log("PERFORMANCE", f"전체 처리 완료: {total_elapsed:.2f}초")

                if prompt is None and debug_mode:
                    debug_logger.add_log("PROMPT", "프롬프트 정보가 제공되지 않았음")

                if keywords:
                    st.markdown("### 🎯 Keywords")
                    if isinstance(keywords, list):
                        st.write(", ".join(str(k) for k in keywords))
                    else:
                        st.write(str(keywords))

                if references:
                    st.markdown("### 📚 관련 뉴스 목록")
                    for item in references:
                        idx = item.get("index", 0)
                        title = item.get("title", "제목 없음")
                        author = item.get("author", "알 수 없음")
                        publish_date = item.get("publishDate", "")[:10]
                        content = item.get("content", "")
                        summary = content[:200] + "..." if len(content) > 200 else content
                        link = item.get("link", "")
                        with st.expander(f"{idx}. {title}"):
                            st.write(f"**작성자:** {author}")
                            st.write(f"**출판일:** {publish_date}")
                            st.write(f"**본문 (요약):** {summary}")
                            if link:
                                st.markdown(f"[기사 원문 보기]({link})")
                            else:
                                st.write("*링크 없음*")
                            st.markdown("**출처: 조선일보**")
                else:
                    st.warning("⚠ 관련 뉴스가 없습니다.")

        except requests.exceptions.Timeout:
            error_msg = "요청이 시간 내에 처리되지 않았습니다. 잠시 후 다시 시도해 주세요."
            st.error(f"❌ {error_msg}")
            if debug_mode:
                debug_logger.add_log("ERROR", "API 타임아웃")

        except requests.exceptions.HTTPError as http_err:
            error_msg = f"HTTP 오류: 상태 코드 {resp.status_code} - {http_err}"
            st.error(error_msg)
            if debug_mode:
                debug_logger.add_log("ERROR", f"HTTP 오류: {http_err}")

        except Exception as e:
            error_msg = f"오류 발생: {e}"
            st.error(error_msg)
            if debug_mode:
                debug_logger.add_log("ERROR", f"예상치 못한 오류: {str(e)}")

        finally:
            if total_elapsed is None:
                total_elapsed = time.time() - start_time
                time_placeholder.success(f"✅ 전체 소요 시간: {total_elapsed:.2f}초")


if __name__ == "__main__":
    main()
