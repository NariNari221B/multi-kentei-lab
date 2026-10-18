import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go
import plotly.express as px
from collections import defaultdict
import json
import urllib.parse
import re
import random
from datetime import date, datetime, timedelta
from database import supabase

st.set_page_config(page_title="マルチ検定ラボ", page_icon="🎓", layout="centered")

# --- 1. セッション状態の初期化 ---
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
if "user_bookmarks" not in st.session_state:
    st.session_state.user_bookmarks = set()
if "is_interrupted" not in st.session_state:
    st.session_state.is_interrupted = False

# --- 2. 認証・データロード関数 ---
def login(email, password):
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.user = response.user
        load_bookmarks(response.user.id)
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

def load_bookmarks(user_id):
    res = supabase.table("bookmarks").select("question_id").eq("user_id", user_id).execute()
    st.session_state.user_bookmarks = set(row["question_id"] for row in res.data)

def toggle_bookmark(user_id, question_id, is_bookmarked):
    if is_bookmarked:
        supabase.table("bookmarks").insert({"user_id": user_id, "question_id": question_id}).execute()
        st.session_state.user_bookmarks.add(question_id)
    else:
        supabase.table("bookmarks").delete().eq("user_id", user_id).eq("question_id", question_id).execute()
        st.session_state.user_bookmarks.discard(question_id)

def update_streak_and_counts(user_id, solved_count):
    if solved_count <= 0:
        return
    today = date.today()
    res = supabase.table("profiles").select("last_study_date, current_streak, today_count").eq("id", user_id).execute()
    if res.data:
        profile = res.data[0]
        last_date_str = profile.get("last_study_date")
        streak = profile.get("current_streak") or 0
        today_count = profile.get("today_count") or 0
        
        if last_date_str:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            if last_date == today:
                today_count += solved_count
            elif (today - last_date).days == 1:
                streak += 1
                today_count = solved_count
            else:
                streak = 1
                today_count = solved_count
        else:
            streak = 1
            today_count = solved_count
            
        supabase.table("profiles").update({
            "last_study_date": str(today),
            "current_streak": streak,
            "today_count": today_count
        }).eq("id", user_id).execute()

# --- 3. 動画マスキング関数 ---
def time_to_seconds(t_str):
    if not t_str: return None
    try:
        parts = list(map(int, t_str.split(':')))
        if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2]
        elif len(parts) == 2: return parts[0]*60 + parts[1]
        elif len(parts) == 1: return parts[0]
    except: return None
    return None

def render_masked_video(video_url: str):
    if video_url.count('?') > 1:
        first_q = video_url.find('?')
        video_url = video_url[:first_q + 1] + video_url[first_q + 1:].replace('?', '&')
    pattern = r'(?:v=|\/embed\/|\/v\/|youtu\.be\/|\/shorts\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, video_url)
    if not match:
        st.error("⚠️ YouTube動画のIDが取得できませんでした。")
        return
    video_id = match.group(1)
    parsed = urllib.parse.urlparse(video_url)
    qs = urllib.parse.parse_qs(parsed.query)
    start_sec = time_to_seconds(qs.get('start_time', [''])[0]) if 'start_time' in qs else None
    end_sec = time_to_seconds(qs.get('end_time', [''])[0]) if 'end_time' in qs else None
    loop_count = int(qs.get('loops', ['3'])[0])
    start_val = start_sec if start_sec is not None else 0

    embed_params = ["enablejsapi=1", "autoplay=0", "controls=0", "disablekb=1", "modestbranding=1", "rel=0", "playsinline=1"]
    if start_sec is not None: embed_params.append(f"start={start_sec}")
    if end_sec is not None: embed_params.append(f"end={end_sec}")
    embed_src = f"https://www.youtube.com/embed/{video_id}?" + "&".join(embed_params)

    html_code = f"""
    <div style="position: relative; width: 100%; max-width: 640px; margin: 0 auto; aspect-ratio: 16/9; overflow: hidden; border-radius: 8px;">
        <iframe id="ytplayer" src="{embed_src}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none;" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"></iframe>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: transparent; z-index: 10;"></div>
        <div style="position: absolute; top: 0; left: 0; width: 100%; height: 40px; background-color: #000000; pointer-events: none; z-index: 20;"></div>
    </div>
    <div style="text-align: center; margin-top: 12px;">
        <button id="play-btn" onclick="startVideo()" style="padding: 10px 24px; font-size: 15px; font-weight: bold; border-radius: 6px; background-color: #1E88E5; color: white; border: none; cursor: pointer; transition: 0.2s;">
            ▶ 動画を再生する（{loop_count}回自動再生）
        </button>
    </div>
    <script>
      var player; var playCount = 0; var maxPlays = {loop_count}; var startSeconds = {start_val}; var isPlaying = false;
      function initPlayer() {{ if (window.YT && window.YT.Player) {{ player = new YT.Player('ytplayer', {{ events: {{ 'onStateChange': onPlayerStateChange }} }}); }} else {{ setTimeout(initPlayer, 200); }} }}
      function startVideo() {{ if (player && !isPlaying) {{ isPlaying = true; playCount = 0; var btn = document.getElementById('play-btn'); btn.disabled = true; btn.style.backgroundColor = '#9E9E9E'; btn.innerText = '⏳ 再生中...'; player.seekTo(startSeconds); player.playVideo(); }} }}
      function onPlayerStateChange(event) {{ if (event.data === 0) {{ playCount++; if (playCount < maxPlays) {{ player.seekTo(startSeconds); player.playVideo(); }} else {{ isPlaying = false; var btn = document.getElementById('play-btn'); btn.disabled = false; btn.style.backgroundColor = '#1E88E5'; btn.innerText = '▶ もう一度再生する'; }} }} }}
      if (!window.YT) {{ var tag = document.createElement('script'); tag.src = "https://www.youtube.com/iframe_api"; var firstScriptTag = document.getElementsByTagName('script')[0]; firstScriptTag.parentNode.insertBefore(tag, firstScriptTag); }}
      initPlayer();
    </script>
    """
    components.html(html_code, height=430)

# --- 4. 採点 & 解答履歴保存処理 ---
def save_quiz_results(user_id, user_answers):
    if not user_answers:
        return 0
    history_records = []
    correct_count = 0
    for ans in user_answers:
        detailed_result = None
        if ans["format_type"] == "multi-dropdown":
            target_correct = ans["correct_answer"]
            if isinstance(target_correct, str): target_correct = json.loads(target_correct)
            detailed = {}
            all_correct = True
            for key, correct_val in target_correct.items():
                user_val = ans["user_answer"].get(key)
                is_key_correct = (user_val == correct_val)
                detailed[key] = is_key_correct
                if not is_key_correct: all_correct = False
            is_correct = all_correct
            detailed_result = detailed
            ans["detailed_result"] = detailed
        else:
            is_correct = (str(ans["user_answer"]).strip().lower() == str(ans["correct_answer"]).strip().lower())
            
        ans["is_correct"] = is_correct
        if is_correct: correct_count += 1
            
        history_records.append({
            "user_id": user_id,
            "question_id": ans["question_id"],
            "is_correct": is_correct,
            "detailed_result": detailed_result,
            "confidence": ans.get("confidence")
        })
    if history_records:
        supabase.table("answer_history").insert(history_records).execute()
    return correct_count

# --- 5. 弱点分析・グラフ描画 ---
def render_analytics_report(user_id, default_exam_id=None):
    exams_res = supabase.table("exams").select("id, name").execute()
    exams = exams_res.data
    if not exams: return st.info("検定データがありません。")
    
    exam_options = {"すべての検定 (総合)": None}
    for exam in exams: exam_options[exam["name"]] = exam["id"]
    
    # デフォルトで特定の検定を選択状態にする
    default_index = 0
    if default_exam_id:
        for idx, (name, eid) in enumerate(exam_options.items()):
            if eid == default_exam_id:
                default_index = idx
                break
                
    selected_exam_name = st.selectbox("📊 分析する対象を選択してください", options=list(exam_options.keys()), index=default_index, key="analytics_exam_selector")
    selected_exam_id = exam_options[selected_exam_name]
    
    res = supabase.table("answer_history").select("is_correct, detailed_result, questions(exam_id, knowledge_category, format_type)").eq("user_id", user_id).execute()
    history_data = res.data
    if not history_data: return st.info("💡 まだ解答履歴データがありません。")
    filtered_data = [r for r in history_data if r.get("questions") and (selected_exam_id is None or r["questions"].get("exam_id") == selected_exam_id)]
    if not filtered_data: return st.warning(f"「{selected_exam_name}」の受験履歴がありません。")

    cat_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    fmt_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    fmt_map = {"4-choice": "4択問題", "text-input": "穴埋め記述", "video-4-choice": "動画付き4択", "video-text-input": "動画付き穴埋め", "image-4-choice": "画像付き4択", "image-text-input": "画像付き穴埋め", "multi-dropdown": "複数穴埋め"}
    total_items, correct_items = 0, 0
    for record in filtered_data:
        q = record.get("questions")
        is_correct, detailed = record["is_correct"], record.get("detailed_result")
        category, fmt = q.get("knowledge_category", "未分類"), fmt_map.get(q.get("format_type"), q.get("format_type", "その他"))
        if detailed:
            for key, key_is_correct in detailed.items():
                cat_stats[category]["total"] += 1; fmt_stats[fmt]["total"] += 1; total_items += 1
                if key_is_correct: cat_stats[category]["correct"] += 1; fmt_stats[fmt]["correct"] += 1; correct_items += 1
        else:
            cat_stats[category]["total"] += 1; fmt_stats[fmt]["total"] += 1; total_items += 1
            if is_correct: cat_stats[category]["correct"] += 1; fmt_stats[fmt]["correct"] += 1; correct_items += 1

    overall_accuracy = int((correct_items / total_items) * 100) if total_items > 0 else 0
    m1, m2, m3 = st.columns(3)
    m1.metric("解答問題数", f"{len(filtered_data)} 問")
    m2.metric("実質正答数", f"{correct_items} / {total_items}")
    m3.metric("総合正答率", f"{overall_accuracy} %")
    st.divider()

    st.write("### 🎯 知識分野別の正答率")
    categories = list(cat_stats.keys())
    cat_accuracies = [int((cat_stats[c]["correct"] / cat_stats[c]["total"]) * 100) for c in categories]
    if categories:
        fig_radar = go.Figure(data=go.Scatterpolar(r=cat_accuracies + [cat_accuracies[0]], theta=categories + [categories[0]], fill='toself', line_color='#1E88E5'))
        fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])), showlegend=False, margin=dict(t=20, b=20, l=40, r=40))
        st.plotly_chart(fig_radar, use_container_width=True)

    st.write("### 📝 出題形式別の正答率")
    formats = list(fmt_stats.keys())
    fmt_accuracies = [int((fmt_stats[f]["correct"] / fmt_stats[f]["total"]) * 100) for f in formats]
    if formats:
        fig_bar = px.bar(x=formats, y=fmt_accuracies, labels={'x': '出題形式', 'y': '正答率 (%)'}, range_y=[0, 100], text=[f"{v}%" for v in fmt_accuracies], color=fmt_accuracies, color_continuous_scale="Blues")
        fig_bar.update_traces(textposition='outside')
        fig_bar.update_layout(showlegend=False, coloraxis_showscale=False, margin=dict(t=30, b=20))
        st.plotly_chart(fig_bar, use_container_width=True)


# --- 6. 画面UI (メインループ) ---
st.title("🎓 マルチ検定ラボ")

if st.session_state.user is None:
    st.write("### アカウントにログイン")
    tab1, tab2 = st.tabs(["ログイン", "新規登録"])
    with tab1:
        login_email = st.text_input("メールアドレス", key="login_email")
        login_password = st.text_input("パスワード", type="password", key="login_password")
        if st.button("ログイン"): login(login_email, login_password)
    with tab2:
        signup_username = st.text_input("ユーザー名（表示名）", key="signup_username")
        signup_email = st.text_input("メールアドレス", key="signup_email")
        signup_password = st.text_input("パスワード (6文字以上)", type="password", key="signup_password")
        if st.button("登録"): sign_up(signup_email, signup_password, signup_username)

else:
    if "user_bookmarks" not in st.session_state or not st.session_state.user_bookmarks:
        load_bookmarks(st.session_state.user.id)

    if not st.session_state.quiz_started:
        profile_res = supabase.table("profiles").select("username, target_exam_id, target_exam_date, last_study_date, current_streak, today_count, daily_goal").eq("id", st.session_state.user.id).execute()
        profile_data = profile_res.data[0] if profile_res.data else {}
        username = profile_data.get("username", "ゲスト")
        
        # --- 学習トラッカー表示 ---
        streak = profile_data.get("current_streak") or 0
        today_count = profile_data.get("today_count") or 0
        last_date_str = profile_data.get("last_study_date")
        daily_goal = profile_data.get("daily_goal") or 5
        
        if last_date_str:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            if last_date != date.today(): today_count = 0
            
        c1, c2 = st.columns([3, 1])
        with c1: st.write(f"ようこそ、**{username}** さん！")
        with c2: 
            if st.button("ログアウト", use_container_width=True): logout()
            
        st.write("#### 📊 あなたの学習トラッカー")
        m1, m2 = st.columns(2)
        m1.metric("🔥 連続学習日数", f"{streak} 日")
        m2.metric("🎯 今日の目標達成度", f"{today_count} / {daily_goal} 問")
        progress = min(today_count / daily_goal, 1.0) if daily_goal > 0 else 0
        st.progress(progress)
        if progress >= 1.0: st.success("🌟 今日の目標を達成しました！素晴らしい継続力です！")

        # --- 目標日数 ---
        exams_res = supabase.table("exams").select("*").execute()
        exams = exams_res.data or []
        exam_id_to_name = {e["id"]: e["name"] for e in exams}
        target_exam_id = profile_data.get("target_exam_id")
        target_exam_date_str = profile_data.get("target_exam_date")
        
        days_left = None
        if target_exam_date_str and target_exam_id in exam_id_to_name:
            target_date = datetime.strptime(target_exam_date_str, "%Y-%m-%d").date()
            days_left = (target_date - date.today()).days
            exam_name = exam_id_to_name[target_exam_id]

            if days_left > 0: st.info(f"🎯 **目標: {exam_name}** ｜ 試験日: **{target_date.strftime('%Y年%m月%d日')}**（本番まであと **{days_left} 日**）")
            elif days_left == 0: st.success(f"🎉 **目標: {exam_name}** ｜ **本日が試験本番です！実力を発揮してきてください！**")
            else: st.warning(f"⚠️ **目標: {exam_name}** ｜ 設定された試験日（{target_date.strftime('%Y年%m月%d日')}）は終了しました。")

        with st.expander("📅 試験予定日・学習目標の設定"):
            if exams:
                target_exam_map = {e["name"]: e["id"] for e in exams}
                current_exam_idx = list(target_exam_map.keys()).index(exam_id_to_name[target_exam_id]) if target_exam_id in exam_id_to_name else 0
                selected_t_exam_name = st.selectbox("目標とする検定", options=list(target_exam_map.keys()), index=current_exam_idx)
                default_date = datetime.strptime(target_exam_date_str, "%Y-%m-%d").date() if target_exam_date_str else date.today()
                selected_t_date = st.date_input("試験予定日", value=default_date, min_value=date.today())
                new_goal = st.number_input("1日の目標問題数", min_value=1, max_value=100, value=daily_goal)

                if st.button("設定を保存する", type="primary"):
                    supabase.table("profiles").update({
                        "target_exam_id": target_exam_map[selected_t_exam_name],
                        "target_exam_date": str(selected_t_date),
                        "daily_goal": new_goal
                    }).eq("id", st.session_state.user.id).execute()
                    st.success("設定を更新しました！")
                    st.rerun()

        st.divider()

        main_tab1, main_tab2 = st.tabs(["📝 検定受験", "📊 弱点分析レポート"])
        
        with main_tab1:
            st.write("### 受験する検定とモードを選択")
            if not exams:
                st.warning("現在、受験可能な検定がありません。")
            else:
                exam_options = {exam["name"]: exam for exam in exams}
                selected_exam_name = st.selectbox("検定一覧", options=list(exam_options.keys()))
                selected_exam = exam_options[selected_exam_name]
                
                base_modes = [
                    "📘 【単元集中】分野別基礎固め",
                    "🔀 【交差出題】全範囲シャッフル演習",
                    "🔥 【弱点特訓】ミス問・自信なし・未解答",
                    "⚡ 【高速復習】完全に理解している問題の総点検",
                    "🔖 【直前対策】ブックマークした問題だけを解く"
                ]
                recommend_idx = 0
                if days_left is not None:
                    if days_left >= 60: recommend_idx = 0
                    elif 21 <= days_left <= 59: recommend_idx = 1
                    elif 7 <= days_left <= 20: recommend_idx = 2
                    else: recommend_idx = 3
                
                display_modes = [f"{m} 🌟今のおすすめ！" if i == recommend_idx and days_left is not None else m for i, m in enumerate(base_modes)]
                selected_display_mode = st.selectbox("学習メソッド（出題モード）を選択してください", options=display_modes, index=recommend_idx if days_left is not None else 0)
                selected_mode_idx = display_modes.index(selected_display_mode)
                
                if st.button("この条件でスタート！", type="primary"):
                    q_res = supabase.table("questions").select("*").eq("exam_id", selected_exam["id"]).execute()
                    all_questions = q_res.data
                    
                    if not all_questions:
                        st.error("この検定にはまだ問題が登録されていません。")
                    else:
                        target_questions = all_questions.copy()
                        
                        if selected_mode_idx == 0:
                            target_questions = sorted(target_questions, key=lambda q: (q.get("knowledge_category", ""), q.get("id", 0)))
                        elif selected_mode_idx == 1:
                            random.shuffle(target_questions)
                        elif selected_mode_idx in [2, 3]:
                            hist_res = supabase.table("answer_history").select("question_id, is_correct, confidence").eq("user_id", st.session_state.user.id).execute()
                            perfect_q_ids = set([h["question_id"] for h in hist_res.data if h.get("is_correct") and h.get("confidence") == "自信あり！"])
                            
                            if selected_mode_idx == 2:
                                target_questions = [q for q in target_questions if q["id"] not in perfect_q_ids]
                                if not target_questions:
                                    st.success("🎉 素晴らしい！すべての問題を完全に理解しています！「高速復習」に挑戦しましょう。")
                                    st.stop()
                            else:
                                target_questions = [q for q in target_questions if q["id"] in perfect_q_ids]
                                if not target_questions:
                                    st.warning("⚠️ まだ「自信あり！」で正解した問題がありません。まずは他のモードで学習しましょう！")
                                    st.stop()
                            random.shuffle(target_questions)
                        elif selected_mode_idx == 4:
                            target_questions = [q for q in target_questions if q["id"] in st.session_state.user_bookmarks]
                            if not target_questions:
                                st.warning("⚠️ ブックマークされている問題がありません。出題画面の 📌 ボタンで追加できます。")
                                st.stop()
                            random.shuffle(target_questions)
                        
                        st.session_state.current_exam = selected_exam
                        st.session_state.questions = target_questions
                        st.session_state.current_q_idx = 0
                        st.session_state.user_answers = []
                        st.session_state.quiz_saved = False
                        st.session_state.is_interrupted = False
                        st.session_state.quiz_started = True
                        st.rerun()

        with main_tab2:
            st.write("### 累計解答データ分析")
            render_analytics_report(st.session_state.user.id)

    else:
        questions = st.session_state.questions
        q_idx = st.session_state.current_q_idx
        total_q = len(questions)
        
        # --- 全問終了 または 途中中断時（結果・解説・即時分析画面） ---
        if q_idx >= total_q or st.session_state.is_interrupted:
            if not st.session_state.quiz_saved:
                st.session_state.correct_count = save_quiz_results(st.session_state.user.id, st.session_state.user_answers)
                update_streak_and_counts(st.session_state.user.id, len(st.session_state.user_answers))
                st.session_state.quiz_saved = True
            
            answered_count = len(st.session_state.user_answers)
            if st.session_state.is_interrupted:
                st.warning(f"⏸️ **解答を中断しました。**（全 {total_q} 問中、解き終えた **{answered_count} 問** を記録しました）")
            else:
                st.balloons()
                st.success("🎉 お疲れ様でした！全問の解答が終了し、記録されました。")
            
            # ダッシュボードに戻るボタン
            if st.button("🏠 ダッシュボードに戻る", type="primary", use_container_width=True):
                st.session_state.quiz_started = False
                st.session_state.current_exam = None
                st.session_state.quiz_saved = False
                st.session_state.is_interrupted = False
                st.rerun()

            st.write("")
            st.write("### 🔍 今回の解答一覧と詳細解説")
            for idx, ans in enumerate(st.session_state.user_answers):
                if "detailed_result" in ans and ans["detailed_result"]:
                    correct_keys = sum(1 for v in ans["detailed_result"].values() if v)
                    total_keys = len(ans["detailed_result"])
                    status_icon = "✅ 完全正解" if correct_keys == total_keys else f"⚠️ 部分正解 ({correct_keys}/{total_keys})" if correct_keys > 0 else "❌ 不正解"
                else:
                    status_icon = "✅ 正解" if ans["is_correct"] else "❌ 不正解"

                with st.expander(f"第 {idx+1} 問 ({ans['knowledge_category']}) - {status_icon} [確信度: {ans.get('confidence')}]"):
                    if ans["format_type"] == "multi-dropdown":
                        target_correct = json.loads(ans["correct_answer"]) if isinstance(ans["correct_answer"], str) else ans["correct_answer"]
                        for k in target_correct.keys():
                            u_val = ans["user_answer"].get(k, "未回答")
                            c_val = target_correct.get(k, "")
                            icon = "✅" if ans["detailed_result"].get(k) else "❌"
                            st.write(f"- （{k}） {icon} あなたの回答: `{u_val}` / 正解: `{c_val}`")
                    else:
                        st.write(f"**あなたの回答:** `{ans['user_answer']}`")
                        st.write(f"**正解:** `{ans['correct_answer']}`")
                    
                    explanation = next((q.get("explanation") for q in questions if q["id"] == ans["question_id"]), None)
                    if explanation:
                        st.info(f"💡 **解説:**\n\n{explanation}")
            
            st.divider()
            # ★ 今回の解答結果を含めた最新の弱点分析レポートをその場で展開
            st.write("### 📊 最新の弱点分析レポート（今解いた結果を反映済み）")
            render_analytics_report(st.session_state.user.id, default_exam_id=st.session_state.current_exam["id"] if st.session_state.current_exam else None)
        
        # --- 出題中画面 ---
        else:
            q = questions[q_idx]
            st.caption(f"問題 {q_idx + 1} / {total_q} （分野: {q['knowledge_category']}）")
            st.progress((q_idx + 1) / total_q)
            
            col_q, col_bm = st.columns([4, 1])
            with col_q:
                st.subheader(f"Q. {q['content']}")
            with col_bm:
                is_bm = q["id"] in st.session_state.user_bookmarks
                new_bm = st.checkbox("📌 ブックマーク", value=is_bm, key=f"bm_{q['id']}")
                if new_bm != is_bm:
                    toggle_bookmark(st.session_state.user.id, q["id"], new_bm)
            
            if q["format_type"] in ["video-4-choice", "video-text-input"] and q.get("video_url"):
                render_masked_video(q["video_url"])
            if q["format_type"] in ["image-4-choice", "image-text-input"] and q.get("image_url"):
                st.image(q["image_url"], use_container_width=True)
            
            user_input = None
            if q["format_type"] in ["4-choice", "video-4-choice", "image-4-choice"]:
                choices = q["choices"] if isinstance(q["choices"], list) else []
                user_input = st.radio("回答を選択してください:", choices, key=f"q_{q_idx}")
            elif q["format_type"] == "multi-dropdown":
                dropdown_choices = json.loads(q["choices"]) if isinstance(q["choices"], str) else q["choices"]
                selected_answers = {}
                cols = st.columns(len(dropdown_choices))
                for idx_col, (label, options) in enumerate(dropdown_choices.items()):
                    with cols[idx_col]:
                        selected_answers[label] = st.selectbox(f"（ {label} ）", options=options, key=f"q_{q_idx}_{label}")
                user_input = selected_answers
            else:
                user_input = st.text_input("解答を入力してください:", key=f"q_{q_idx}")
            
            st.write("---")
            confidence = st.select_slider(
                "🤔 この解答の自信は？", 
                options=["自信なし（勘）", "たぶんこれ", "自信あり！"], 
                value="たぶんこれ", 
                key=f"conf_{q_idx}"
            )
            
            st.write("")
            btn_col1, btn_col2 = st.columns([2, 1])
            
            with btn_col1:
                if st.button("回答を送信して次へ ➔", type="primary", use_container_width=True):
                    if not user_input or (isinstance(user_input, str) and user_input.strip() == ""):
                        st.warning("回答を入力・選択してください。")
                    else:
                        st.session_state.user_answers.append({
                            "question_id": q["id"],
                            "knowledge_category": q["knowledge_category"],
                            "format_type": q["format_type"],
                            "user_answer": user_input,
                            "correct_answer": q["correct_answer"],
                            "confidence": confidence
                        })
                        st.session_state.current_q_idx += 1
                        st.rerun()

            with btn_col2:
                # ★ 途中中断・分析ボタン
                if st.button("⏹️ 中断して分析へ", use_container_width=True):
                    if len(st.session_state.user_answers) == 0:
                        st.info("まだ1問も回答していません。ダッシュボードに戻ります。")
                        st.session_state.quiz_started = False
                        st.session_state.current_exam = None
                        st.session_state.quiz_saved = False
                        st.rerun()
                    else:
                        st.session_state.is_interrupted = True
                        st.rerun()