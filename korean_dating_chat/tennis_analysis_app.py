import streamlit as st
import google.generativeai as genai
import os
import tempfile
import time
from pathlib import Path
from dotenv import load_dotenv
import yt_dlp
import re
import cv2

# 환경변수 로드
load_dotenv()

# Gemini API 설정
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

# 파일 및 영상 제한 설정
MAX_FILE_SIZE_MB = 500  # 최대 파일 크기 (MB) - 고화질 1분 영상 대응
MAX_VIDEO_DURATION_MINUTES = 1  # 최대 영상 길이 (분) - API 비용 절감
MAX_DAILY_ANALYSES = 5  # 하루 최대 분석 횟수 (비용 폭탄 방지)

def check_daily_limit():
    """일일 분석 횟수 제한 체크"""
    from datetime import datetime

    # 세션에 분석 기록이 없으면 초기화
    if 'analysis_history' not in st.session_state:
        st.session_state['analysis_history'] = []

    # 오늘 날짜
    today = datetime.now().date()

    # 오늘 분석한 횟수 계산
    today_analyses = [d for d in st.session_state['analysis_history'] if d == today]

    if len(today_analyses) >= MAX_DAILY_ANALYSES:
        st.error(f"⚠️ 일일 분석 한도({MAX_DAILY_ANALYSES}회)에 도달했습니다. 내일 다시 시도해주세요!")
        st.info("💡 비용 절감을 위한 제한입니다. 양해 부탁드립니다.")
        return False

    return True

def record_analysis():
    """분석 기록 추가"""
    from datetime import datetime
    if 'analysis_history' not in st.session_state:
        st.session_state['analysis_history'] = []

    today = datetime.now().date()
    st.session_state['analysis_history'].append(today)

def check_video_duration(file_path):
    """동영상 길이 확인 (초 단위 반환)"""
    try:
        video = cv2.VideoCapture(file_path)
        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = frame_count / fps if fps > 0 else 0
        video.release()
        return duration
    except Exception as e:
        st.warning(f"영상 길이를 확인할 수 없습니다: {str(e)}")
        return None

def validate_video_file(file_path, file_size_bytes=None):
    """동영상 파일 유효성 검사 (크기 및 길이)"""
    # 파일 크기 체크
    if file_size_bytes is None:
        file_size_bytes = os.path.getsize(file_path)

    file_size_mb = file_size_bytes / (1024 * 1024)

    if file_size_mb > MAX_FILE_SIZE_MB:
        st.error(f"⚠️ 파일 크기가 너무 큽니다. (현재: {file_size_mb:.1f}MB, 최대: {MAX_FILE_SIZE_MB}MB)")
        return False

    # 영상 길이 체크
    duration = check_video_duration(file_path)
    if duration is not None:
        duration_minutes = duration / 60

        if duration_minutes > MAX_VIDEO_DURATION_MINUTES:
            st.error(f"⚠️ 영상이 너무 깁니다. (현재: {duration_minutes:.1f}분, 최대: {MAX_VIDEO_DURATION_MINUTES}분)")
            return False

        st.info(f"📊 파일 크기: {file_size_mb:.1f}MB | 영상 길이: {duration_minutes:.1f}분")

    return True

def is_valid_youtube_url(url):
    """유튜브 URL 유효성 검사"""
    youtube_regex = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    return re.match(youtube_regex, url) is not None

def download_youtube_video(youtube_url, output_path, start_time=None, end_time=None):
    """유튜브 동영상 다운로드 (구간 지정 가능)"""
    try:
        ydl_opts = {
            'format': 'best[ext=mp4]',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
        }

        # 구간 지정이 있으면 postprocessor로 잘라내기
        if start_time is not None and end_time is not None:
            ydl_opts['postprocessor_args'] = {
                'ffmpeg': ['-ss', str(start_time), '-to', str(end_time)]
            }
            st.info(f"🔽 유튜브 동영상 다운로드 중... ({start_time}초 ~ {end_time}초 구간)")
        else:
            st.info("🔽 유튜브 동영상 다운로드 중...")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
            st.success("✅ 다운로드 완료!")

        return True
    except Exception as e:
        st.error(f"유튜브 다운로드 오류: {str(e)}")
        return False

def upload_to_gemini(file_path):
    """Gemini API에 비디오 파일 업로드"""
    try:
        video_file = genai.upload_file(path=file_path)
        st.info(f"업로드된 파일 URI: {video_file.uri}")

        # 파일 처리 대기
        while video_file.state.name == "PROCESSING":
            st.info("영상 처리 중...")
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            raise ValueError("영상 처리에 실패했습니다.")

        return video_file
    except Exception as e:
        st.error(f"파일 업로드 오류: {str(e)}")
        return None

def analyze_tennis_posture(video_file):
    """Gemini 1.5 Flash로 테니스 자세 분석"""
    try:
        # Gemini 1.5 Flash 모델 생성
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")

        # 분석 프롬프트
        prompt = """
        이 테니스 영상을 분석해서 다음 형식으로 답변해주세요:

        **장점:**
        (자세의 좋은 점 1가지를 구체적으로 설명)

        **단점:**
        (개선이 필요한 점 1가지를 구체적으로 설명)

        **교정법:**
        (단점을 개선하기 위한 구체적인 방법 1가지)

        답변은 한국어로 작성하고, 전문적이면서도 이해하기 쉽게 설명해주세요.
        """

        # 영상 분석 요청
        response = model.generate_content([video_file, prompt])

        return response.text
    except Exception as e:
        st.error(f"분석 오류: {str(e)}")
        return None

def main():
    # 페이지 설정
    st.set_page_config(
        page_title="테니스 자세 분석 앱",
        page_icon="🎾",
        layout="wide"
    )

    # 제목
    st.title("🎾 테니스 자세 분석 앱")
    st.markdown("---")
    st.write("테니스 영상을 업로드하면 AI가 자세를 분석해드립니다!")

    # API 키 확인
    if not os.getenv('GEMINI_API_KEY'):
        st.error("⚠️ GEMINI_API_KEY가 설정되지 않았습니다. .env 파일에 API 키를 추가해주세요.")
        st.code("GEMINI_API_KEY=your_api_key_here")
        return

    # 사이드바
    with st.sidebar:
        st.header("📋 사용 방법")
        st.markdown("""
        **방법 1: 파일 업로드**
        1. 테니스 동영상 파일을 선택하세요
        2. '분석 시작' 버튼을 클릭하세요

        **방법 2: 유튜브 링크**
        1. 유튜브 URL을 입력하세요
        2. '분석 시작' 버튼을 클릭하세요

        **지원 형식:**
        - MP4, MOV, AVI 등
        - 유튜브 URL
        """)

        st.markdown("---")
        st.header("⚙️ 업로드 제한")
        st.markdown(f"""
        - **최대 파일 크기**: {MAX_FILE_SIZE_MB}MB
        - **최대 영상 길이**: {MAX_VIDEO_DURATION_MINUTES}분

        *API 비용 절감을 위한 제한입니다*
        """)

        # 일일 분석 횟수 표시
        from datetime import datetime
        if 'analysis_history' not in st.session_state:
            st.session_state['analysis_history'] = []

        today = datetime.now().date()
        today_analyses = [d for d in st.session_state['analysis_history'] if d == today]
        remaining = MAX_DAILY_ANALYSES - len(today_analyses)

        st.markdown("---")
        st.header("📊 오늘 남은 분석 횟수")
        st.progress(remaining / MAX_DAILY_ANALYSES)
        st.markdown(f"**{remaining} / {MAX_DAILY_ANALYSES}회** 남음")

        st.markdown("---")
        st.info("💡 Powered by Google Gemini 1.5 Flash")

    # 탭 생성
    tab1, tab2 = st.tabs(["📁 파일 업로드", "🎬 유튜브 URL"])

    # 탭 1: 파일 업로드
    with tab1:
        st.info(f"⚠️ 파일 업로드는 **{MAX_VIDEO_DURATION_MINUTES}분 이내** 영상만 가능합니다. 긴 영상은 미리 편집해서 올려주세요!")

        uploaded_file = st.file_uploader(
            f"{MAX_VIDEO_DURATION_MINUTES}분 이내의 테니스 동영상을 업로드하세요",
            type=['mp4', 'mov', 'avi', 'mkv', 'wmv'],
            help="동영상 파일을 선택해주세요"
        )

        if uploaded_file is not None:
            col1, col2 = st.columns([1, 1])

            with col1:
                st.subheader("📹 업로드된 영상")
                st.video(uploaded_file)

            with col2:
                st.subheader("🔍 분석 결과")

                if st.button("🚀 분석 시작", key="file_analyze", type="primary", use_container_width=True):
                    # 일일 분석 횟수 제한 체크
                    if not check_daily_limit():
                        st.stop()

                    # 임시 파일로 저장
                    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
                        tmp_file.write(uploaded_file.getvalue())
                        tmp_path = tmp_file.name

                    try:
                        # 파일 유효성 검사
                        if not validate_video_file(tmp_path, len(uploaded_file.getvalue())):
                            return  # 검증 실패 시 중단

                        with st.spinner("영상을 분석 중입니다... 잠시만 기다려주세요."):
                            video_file = upload_to_gemini(tmp_path)

                            if video_file:
                                analysis_result = analyze_tennis_posture(video_file)

                                if analysis_result:
                                    # 분석 성공 시 기록
                                    record_analysis()

                                    st.success("✅ 분석 완료!")
                                    st.markdown("---")
                                    st.markdown(analysis_result)
                                    st.session_state['last_analysis'] = analysis_result
                    finally:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)

                if 'last_analysis' in st.session_state:
                    st.info("📝 마지막 분석 결과")
                    st.markdown(st.session_state['last_analysis'])
        else:
            st.info("👆 위의 업로드 버튼을 클릭하여 테니스 동영상을 선택해주세요.")

    # 탭 2: 유튜브 URL
    with tab2:
        st.success("✨ 유튜브는 긴 영상도 OK! 원하는 구간만 잘라서 분석합니다.")

        youtube_url = st.text_input(
            "유튜브 URL을 입력하세요",
            placeholder="https://www.youtube.com/watch?v=...",
            help="유튜브 동영상 링크를 붙여넣으세요"
        )

        # 구간 지정 옵션
        use_clip = st.checkbox("✂️ 구간 지정하기 (특정 부분만 분석)", value=False)

        start_time = 0
        end_time = 60

        if use_clip:
            col_start, col_end = st.columns(2)
            with col_start:
                start_time = st.number_input(
                    "⏱️ 시작 시간 (초)",
                    min_value=0,
                    value=0,
                    step=1,
                    help="분석 시작할 시간을 초 단위로 입력"
                )
            with col_end:
                end_time = st.number_input(
                    "⏱️ 끝 시간 (초)",
                    min_value=1,
                    value=60,
                    step=1,
                    help="분석 끝낼 시간을 초 단위로 입력"
                )

            # 구간 길이 검증
            duration_seconds = end_time - start_time
            if duration_seconds > MAX_VIDEO_DURATION_MINUTES * 60:
                st.warning(f"⚠️ 구간 길이가 {MAX_VIDEO_DURATION_MINUTES}분({MAX_VIDEO_DURATION_MINUTES * 60}초)을 초과합니다. (현재: {duration_seconds}초)")
            elif duration_seconds <= 0:
                st.error("⚠️ 끝 시간이 시작 시간보다 커야 합니다!")
            else:
                st.info(f"📊 분석할 구간: {start_time}초 ~ {end_time}초 ({duration_seconds}초)")

        if youtube_url:
            if is_valid_youtube_url(youtube_url):
                col1, col2 = st.columns([1, 1])

                with col1:
                    st.subheader("🎬 유튜브 영상")

                    # 구간 지정 시 URL에 타임스탬프 추가
                    if use_clip and start_time > 0:
                        display_url = f"{youtube_url}&t={int(start_time)}s"
                        st.video(display_url)
                    else:
                        st.video(youtube_url)

                with col2:
                    st.subheader("🔍 분석 결과")

                    if st.button("🚀 분석 시작", key="youtube_analyze", type="primary", use_container_width=True):
                        # 일일 분석 횟수 제한 체크
                        if not check_daily_limit():
                            st.stop()

                        # 구간 길이 검증
                        duration_seconds = end_time - start_time
                        if duration_seconds <= 0:
                            st.error("⚠️ 끝 시간이 시작 시간보다 커야 합니다!")
                            st.stop()

                        if duration_seconds > MAX_VIDEO_DURATION_MINUTES * 60:
                            st.error(f"⚠️ 구간 길이가 {MAX_VIDEO_DURATION_MINUTES}분을 초과합니다!")
                            st.stop()

                        # 임시 파일 경로 생성
                        tmp_path = os.path.join(tempfile.gettempdir(), f"tennis_video_{int(time.time())}.mp4")

                        try:
                            # 유튜브 동영상 다운로드 (구간 지정)
                            if use_clip:
                                download_success = download_youtube_video(youtube_url, tmp_path, start_time, end_time)
                            else:
                                download_success = download_youtube_video(youtube_url, tmp_path)

                            if download_success:
                                # 파일 유효성 검사
                                if not validate_video_file(tmp_path):
                                    return  # 검증 실패 시 중단

                                with st.spinner("영상을 분석 중입니다... 잠시만 기다려주세요."):
                                    # Gemini에 업로드
                                    video_file = upload_to_gemini(tmp_path)

                                    if video_file:
                                        # 자세 분석
                                        analysis_result = analyze_tennis_posture(video_file)

                                        if analysis_result:
                                            # 분석 성공 시 기록
                                            record_analysis()

                                            st.success("✅ 분석 완료!")
                                            st.markdown("---")
                                            st.markdown(analysis_result)
                                            st.session_state['last_analysis'] = analysis_result
                        finally:
                            # 임시 파일 삭제
                            if os.path.exists(tmp_path):
                                os.unlink(tmp_path)

                    if 'last_analysis' in st.session_state:
                        st.info("📝 마지막 분석 결과")
                        st.markdown(st.session_state['last_analysis'])
            else:
                st.error("⚠️ 유효하지 않은 유튜브 URL입니다. 올바른 유튜브 링크를 입력해주세요.")
        else:
            st.info("👆 위의 입력창에 유튜브 URL을 붙여넣으세요.")

if __name__ == "__main__":
    main()
