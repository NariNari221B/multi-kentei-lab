import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import plotly.express as px
from collections import defaultdict
import json
from database import supabase

st.set_page_config(page_title="マルチ検定ラボ", page_icon="🎓", layout="centered")

# 1. セッション状態の初期化
if "user" not in st.session_state:
    st.session_state.user = None
if "current_exam" not in st.session_state:
    st.session_state.current_exam = None
if "quiz_started" not in st.session_state:
    st.session_state.quiz_started = False
if "questions" not in st.session_state:
    st.session_state.questions = []
if "current_q_idx" not in st.session_state:
    st.session_state.current_q_idx = 0
if "user_answers" not in st.session_state:
    st.session_state.user_answers = []
if "quiz_saved" not in st.session_state:
    st.session_state.quiz_saved = False

# --- 認証関数 ---
def login(email, password):
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.user = response.user
        st.success("ログインに成功しました！")
        st.rerun()
    except Exception:
        st.error("ログイン失敗: メールアドレスかパスワードが間違っています。")

def sign_up(email, password, username):
    try:
        response = supabase.auth.sign_up({"email": email, "password": password})
        if response.user:
            supabase.table("profiles").insert({
                "id": response.user.id,
                "username": username
            }).execute()
            st.success("アカウント登録が完了しました！ログインしてください。")
    except Exception as e:
        st.error(f"登録失敗: {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.clear()
    st.rerun()

# --- 動画マスキング描画関数 ---
def render_masked_video(video_url: str):
    html_code = f"""
    <div style="position: relative; width: 100%; max-width: 640px; margin: 0 auto; aspect-ratio: 16/9; overflow: hidden; border-radius: 8px;">
        <iframe 
            src="{video_url}?autoplay=0&controls=1&modestbranding=1" 
            style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none;"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
            allowfullscreen>
        </iframe>
        <div style="position: absolute; bottom: 0; left: 0; width: 100%; height: 15%; background-color: #000000; pointer-events: none;"></div>
    </div>
    """
    components.html(html_code, height=380)

# --- 採点 & 解答履歴保存処理 ---
def save_quiz_results(user_id, user_answers):
    history_records = []
    correct_count = 0
    
    for ans in user_answers:
        # multi-dropdown 形式の場合は全一致で正誤判定
        if ans["format_type"] == "multi-dropdown":
            target_correct = ans["correct_answer"]
            if isinstance(target_correct, str):
                target_correct = json.loads(target_correct)
            is_correct = (ans["user_answer"] == target_correct)
        else:
            is_correct = (str(ans["user_answer"]).strip().lower() == str(ans["correct_answer"]).strip().lower())
            
        ans["is_correct"] = is_correct
        if is_correct:
            correct_count += 1
            
        history_records.append({
            "user_id": user_id,
            "question_id": ans["question_id"],
            "is_correct": is_correct
        })
    
    if history_records:
        supabase.table("answer_history").insert(history_records).execute()
        
    return correct_count

# --- 弱点分析データの取得・グラフ描画処理 ---
def render_analytics_report(user_id):
    res = supabase.table("answer_history").select("is_correct, questions(knowledge_category, format_type)").eq("user_id", user_id).execute()
    history_data = res.data
    
    if not history_data:
        st.info("💡 まだ解答履歴データがありません。検定を受験するとここに弱点分析レポートが表示されます！")
        return

    cat_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    fmt_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    
    fmt_map = {
        "4-choice": "4択問題",
        "text-input": "穴埋め記述",
        "video-4-choice": "動画付き4択",
        "video-text-input": "動画付き穴埋め",
        "multi-dropdown": "複数穴埋め"
    }

    for record in history_data:
        q = record.get("questions")
        if not q:
            continue
        
        is_correct = record["is_correct"]
        category = q.get("knowledge_category", "未分類")
        fmt = fmt_map.get(q.get("format_type"), q.get("format_type", "その他"))
        
        cat_stats[category]["total"] += 1
        if is_correct:
            cat_stats[category]["correct"] += 1
            
        fmt_stats[fmt]["total"] += 1
        if is_correct:
            fmt_stats[fmt]["correct"] += 1

    total_answers = len(history_data)
    total_correct = sum(1 for r in history_data if r["is_correct"])
    overall_accuracy = int((total_correct / total_answers) * 100) if total_answers > 0 else 0
    
    m1, m2, m3 = st.columns(3)
    m1.metric("累計解答数", f"{total_answers} 回")
    m2.metric("累計正解数", f"{total_correct} 回")
    m3.metric("通算正解率", f"{overall_accuracy} %")
    
    st.divider()

    # 1. 知識分野別分析
    st.write("### 🎯 知識分野別の正答率")
    categories = list(cat_stats.keys())
    cat_accuracies = [int((cat_stats[c]["correct"] / cat_stats[c]["total"]) * 100) for c in categories]
    
    r_data = cat_accuracies + [cat_accuracies[0]]
    theta_data = categories + [categories[0]]
    
    fig_radar = go.Figure(
        data=go.Scatterpolar(
            r=r_data,
            theta=theta_data,
            fill='toself',
            name='正答率 (%)',
            line_color='#1E88E5'
        )
    )
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False,
        margin=dict(t=20, b=20, l=40, r=40)
    )
    st.plotly_chart(fig_radar, use_container_width=True)

    # 2. 出題形式別分析
    st.write("### 📝 出題形式別の正答率")
    formats = list(fmt_stats.keys())
    fmt_accuracies = [int((fmt_stats[f]["correct"] / fmt_stats[f]["total"]) * 100) for f in formats]
    
    fig_bar = px.bar(
        x=formats, 
        y=fmt_accuracies,
        labels={'x': '出題形式', 'y': '正答率 (%)'},
        range_y=[0, 100],
        text=[f"{v}%" for v in fmt_accuracies],
        color=fmt_accuracies,
        color_continuous_scale="Blues"
    )
    fig_bar.update_traces(textposition='outside')
    fig_bar.update_layout(showlegend=False, coloraxis_showscale=False, margin=dict(t=30, b=20))
    st.plotly_chart(fig_bar, use_container_width=True)

# --- 画面UI ---
st.title("🎓 マルチ検定ラボ")

# 2. ログインしていない場合の画面
if st.session_state.user is None:
    st.write("### アカウントにログイン")
    
    tab1, tab2 = st.tabs(["ログイン", "新規登録"])
    
    with tab1:
        login_email = st.text_input("メールアドレス", key="login_email")
        login_password = st.text_input("パスワード", type="password", key="login_password")
        if st.button("ログイン"):
            login(login_email, login_password)
            
    with tab2:
        signup_username = st.text_input("ユーザー名（表示名）", key="signup_username")
        signup_email = st.text_input("メールアドレス", key="signup_email")
        signup_password = st.text_input("パスワード (6文字以上)", type="password", key="signup_password")
        if st.button("登録"):
            if not signup_email or not signup_password:
                st.warning("⚠️ メールアドレスとパスワードを入力してください。")
            else:
                sign_up(signup_email, signup_password, signup_username)

# 3. ログインしている場合の画面
else:
    # --- A. クイズ開始前（メインダッシュボード） ---
    if not st.session_state.quiz_started:
        profile_res = supabase.table("profiles").select("username").eq("id", st.session_state.user.id).execute()
        username = profile_res.data[0]["username"] if profile_res.data else "ゲスト"
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"ようこそ、**{username}** さん！")
        with col2:
            if st.button("ログアウト", use_container_width=True):
                logout()
        
        st.divider()
        
        main_tab1, main_tab2 = st.tabs(["📝 検定受験", "📊 弱点分析レポート"])
        
        # --- タブ1: 検定選択 & 開始 ---
        with main_tab1:
            st.write("### 受験する検定を選択")
            exams_res = supabase.table("exams").select("*").execute()
            exams = exams_res.data
            
            if not exams:
                st.warning("現在、受験可能な検定がありません。")
            else:
                exam_options = {exam["name"]: exam for exam in exams}
                selected_exam_name = st.selectbox("検定一覧", options=list(exam_options.keys()))
                selected_exam = exam_options[selected_exam_name]
                
                st.info(f"**詳細:** {selected_exam['description']}")
                
                if st.button("この検定を開始する", type="primary"):
                    q_res = supabase.table("questions").select("*").eq("exam_id", selected_exam["id"]).execute()
                    if not q_res.data:
                        st.error("この検定にはまだ問題が登録されていません。")
                    else:
                        st.session_state.current_exam = selected_exam
                        st.session_state.questions = q_res.data
                        st.session_state.current_q_idx = 0
                        st.session_state.user_answers = []
                        st.session_state.quiz_saved = False
                        st.session_state.quiz_started = True
                        st.rerun()

        # --- タブ2: 弱点分析レポート ---
        with main_tab2:
            st.write("### 累計解答データ分析")
            render_analytics_report(st.session_state.user.id)

    # --- B. クイズ実行 Engine ＆ 採点結果画面 ---
    else:
        questions = st.session_state.questions
        q_idx = st.session_state.current_q_idx
        total_q = len(questions)
        
        # すべて解き終わった場合
        if q_idx >= total_q:
            if not st.session_state.quiz_saved:
                st.session_state.correct_count = save_quiz_results(
                    st.session_state.user.id, 
                    st.session_state.user_answers
                )
                st.session_state.quiz_saved = True
            
            correct_cnt = st.session_state.correct_count
            score_percent = int((correct_cnt / total_q) * 100)
            
            st.balloons()
            st.success("🎉 お疲れ様でした！すべての解答が終了しました。")
            
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric(label="正解数", value=f"{correct_cnt} / {total_q} 問")
            with col_b:
                st.metric(label="正解率", value=f"{score_percent}%")
            
            st.divider()
            st.write("### 🔍 解答一覧と正誤結果")
            
            for idx, ans in enumerate(st.session_state.user_answers):
                status_icon = "✅ 正解" if ans["is_correct"] else "❌ 不正解"
                with st.expander(f"第 {idx+1} 問 ({ans['knowledge_category']}) - {status_icon}"):
                    # 辞書形式（multi-dropdown）の場合は見やすくテキスト整形
                    if isinstance(ans["user_answer"], dict):
                        user_ans_str = ", ".join([f"{k}: {v}" for k, v in ans["user_answer"].items()])
                        
                        target_correct = ans["correct_answer"]
                        if isinstance(target_correct, str):
                            target_correct = json.loads(target_correct)
                        correct_ans_str = ", ".join([f"{k}: {v}" for k, v in target_correct.items()])
                        
                        st.write(f"**あなたの回答:** `{user_ans_str}`")
                        st.write(f"**正解:** `{correct_ans_str}`")
                    else:
                        st.write(f"**あなたの回答:** `{ans['user_answer']}`")
                        st.write(f"**正解:** `{ans['correct_answer']}`")
            
            st.write("")
            if st.button("ダッシュボードに戻る", type="primary"):
                st.session_state.quiz_started = False
                st.session_state.current_exam = None
                st.session_state.quiz_saved = False
                st.rerun()
        
        # 出題中
        else:
            q = questions[q_idx]
            
            st.caption(f"問題 {q_idx + 1} / {total_q} （分野: {q['knowledge_category']}）")
            st.progress((q_idx + 1) / total_q)
            
            st.subheader(f"Q. {q['content']}")
            
            if q["format_type"] in ["video-4-choice", "video-text-input"] and q.get("video_url"):
                render_masked_video(q["video_url"])
            
            # --- 出題形式に応じたフォーム切り替え ---
            user_input = None
            
            if q["format_type"] in ["4-choice", "video-4-choice"]:
                choices = q["choices"] if isinstance(q["choices"], list) else []
                user_input = st.radio("回答を選択してください:", choices, key=f"q_{q_idx}")
                
            elif q["format_type"] == "multi-dropdown":
                dropdown_choices = q["choices"]
                if isinstance(dropdown_choices, str):
                    dropdown_choices = json.loads(dropdown_choices)
                
                selected_answers = {}
                st.write("各空欄に当てはまる項目を選択してください:")
                cols = st.columns(len(dropdown_choices))
                
                for idx_col, (label, options) in enumerate(dropdown_choices.items()):
                    with cols[idx_col]:
                        selected_answers[label] = st.selectbox(
                            f"（ {label} ）", 
                            options=options, 
                            key=f"q_{q_idx}_{label}"
                        )
                user_input = selected_answers
                
            else:
                user_input = st.text_input("解答を入力してください:", key=f"q_{q_idx}")
            
            st.write("")
            if st.button("回答を送信して次へ ➔", type="primary"):
                if not user_input or (isinstance(user_input, str) and user_input.strip() == ""):
                    st.warning("回答を入力・選択してください。")
                else:
                    st.session_state.user_answers.append({
                        "question_id": q["id"],
                        "knowledge_category": q["knowledge_category"],
                        "format_type": q["format_type"],
                        "user_answer": user_input,
                        "correct_answer": q["correct_answer"]
                    })
                    st.session_state.current_q_idx += 1
                    st.rerun()