import streamlit as st
import httpx

# API configuration
API_URL = "http://127.0.0.1:8000/api/chat"

st.set_page_config(
    page_title="Westside Promotion Intelligence",
    page_icon="🛍️",
    layout="wide"
)

st.title("🛍️ Westside Promotion Intelligence")
st.markdown("""
Welcome to the AI Pricing Strategist! Ask me anything about current market discounts, 
competitor offers, or internal strategies. I will query the database in real-time.
""")

# Initialize chat history inside Streamlit
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# React to user input
if prompt := st.chat_input("Ask about competitor trends or strategies..."):
    # Display user message in chat message container
    st.chat_message("user").markdown(prompt)
    
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Display assistant response placeholder
    with st.chat_message("assistant"):
        with st.spinner("Analyzing market data..."):
            try:
                # Call the FastAPI backend
                response = httpx.post(
                    "http://127.0.0.1:8000/api/chat", 
                    json={"message": prompt},
                    timeout=120.0  # Agent LLM + tool loop can take 60-90s
                )
                
                if response.status_code == 200:
                    answer = response.json().get("response", "Error reading response")
                else:
                    answer = f"⚠️ Server Error: {response.text}"
            except httpx.RequestError as e:
                answer = f"⚠️ Could not connect to API Backend at port 8000. Is the FastAPI server running? Details: {e}"

        st.markdown(answer)
        
    # Add assistant response to chat history
    st.session_state.messages.append({"role": "assistant", "content": answer})
