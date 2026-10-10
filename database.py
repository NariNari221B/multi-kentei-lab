import streamlit as st
from supabase import create_client, Client

@st.cache_resource
def init_connection() -> Client:
    """
    Streamlitのsecretsから設定を読み込み、Supabaseクライアントを初期化します。
    @st.cache_resource により、接続インスタンスをキャッシュしてパフォーマンスを向上させます。
    """
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

# 他のファイルから import して使えるようにする
supabase = init_connection()