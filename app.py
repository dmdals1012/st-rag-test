import streamlit as st
from datetime import datetime

# 기본 테스트
st.title("📰 조선일보 AI POC 시연 - 테스트")
st.write("✅ 앱이 정상적으로 시작되었습니다!")
st.write(f"현재 시간: {datetime.now()}")

# Secrets 테스트
st.subheader("🔐 Secrets 확인")
try:
    if "aws_access_key_id" in st.secrets:
        st.success("✅ aws_access_key_id 찾음")
    else:
        st.error("❌ aws_access_key_id 없음")
        
    if "aws_secret_access_key" in st.secrets:
        st.success("✅ aws_secret_access_key 찾음")
    else:
        st.error("❌ aws_secret_access_key 없음")
        
    # 모든 secret 키 확인
    st.write("설정된 secret 키들:")
    st.write(list(st.secrets.keys()))
    
except Exception as e:
    st.error(f"Secrets 접근 에러: {e}")

# 기본 입력 테스트
question = st.text_input("🔍 검색어 입력 테스트")
if st.button("테스트 버튼"):
    st.write(f"입력값: {question}")
    st.success("버튼 클릭 성공!")