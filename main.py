import asyncio
import os
from dotenv import load_dotenv
import json
import sqlite3
from typing import List, TypedDict, Annotated, Optional
from langchain_core.messages import HumanMessage, AnyMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph.message import add_messages
from langchain_core.prompts import PromptTemplate
from langgraph.graph import StateGraph, END
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from IPython.display import Image, display
from tools import TransactionDetails, DATABASE_FILE, setup_database, extract_transaction_details, create_invoice, get_ledger_data
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

load_dotenv()

        
# -----------------------------------STATE SCHEMA-------------------------------------------
class AgentState(TypedDict):
    
    # Conversation History
    messages: Annotated[list[AnyMessage], add_messages]
 
#--------------------------------------------------------------------------------------------


#-------------------------------------TOOLS---------------------------------------------
local_tools = [
    extract_transaction_details,
    create_invoice,
    get_ledger_data
]


# Initialise the LLM
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
llm_with_tools = None



#------------------------------------AI ASSISTANT---------------------------------------
async def assistant(state: AgentState):
    
    global llm_with_tools
    
    sys_msg = SystemMessage(content=f"""
    You are an intelligent ERP Assistant focused on invoice processing and transaction management.

    Your Workflow:
    1. When user provides transaction text, use extract_transaction_details() to parse it
    2. If extraction succeeds, use create_invoice() to store the data
    3. If user asks to see records, use get_ledger_data() to display them
    4. Always handle errors gracefully and inform users of the result

    Important Rules:
    - Extract EXACT values from user text (don't make up data)
    - Handle currency symbols and numbers correctly
    - Return clear success/failure messages
    - Use proper error handling for invalid data

    Example 1:
    User: "Amazon paid $40000 for 5 GPUs"
    → extract_transaction_details("Amazon paid $40000 for 5 GPUs")
    → create_invoice("Amazon", 40000.0, "GPUs", 5)
    → "Successfully created invoice #123 for Amazon - $40,000 for 5 GPUs"

    Example 2:
    User: "Microsoft bought 10 laptops for $15000"
    → extract_transaction_details("Microsoft bought 10 laptops for $15000")
    → create_invoice("Microsoft", 15000.0, "laptops", 10)
    → "Successfully created invoice #124 for Microsoft - $15,000 for 10 laptops"

    Example 3:
    User: "Show me all transactions"
    → get_ledger_data()
    → [Display formatted ledger table]
    
    """)
    
    response = await llm_with_tools.ainvoke([sys_msg] + state["messages"])
    
    return{
        "messages": [response],
    }

#--------------------------------Build the Graph -----------------------------------------------------
async def build_graph():
    "Build the state graph with peoperly initialized tools and assistant function"
    
    builder = StateGraph(AgentState)
    global llm_with_tools
    
    # 1. Setup Tools - Use local tools only
    llm_with_tools = llm.bind_tools(local_tools)
    
    # 2. Nodes & Edges
    builder.add_node("assistant", assistant)
    builder.add_node("tools", ToolNode(local_tools))
    builder.add_edge(START, "assistant")
    builder.add_conditional_edges("assistant", tools_condition)
    builder.add_edge("tools", "assistant")
    
    # 3. Proper Redis checkpointer with context management
    redis_url = "redis://localhost:6379"
            
    async with AsyncRedisSaver.from_conn_string(redis_url) as checkpointer:
        app = builder.compile(checkpointer=checkpointer)
    
        # Generate PNG image of the graph
        image_data = app.get_graph().draw_mermaid_png()
        with open("graph.png", "wb") as f:
            f.write(image_data)
        
        return app



#---------------------------------------CHAT INTERFACE-----------------------------------------
async def chat_interface(graph):
    # Initialize database
    await setup_database()
    
    print("""
          
██╗███╗░░██╗██╗░░░██╗░█████╗░██╗░█████╗░███████╗
██║████╗░██║██║░░░██║██╔══██╗██║██╔══██╗██╔════╝
██║██╔██╗██║╚██╗░██╔╝██║░░██║██║██║░░╚═╝█████╗░░
██║██║╚████║░╚████╔╝░██║░░██║██║██║░░██╗██╔══╝░░
██║██║░╚███║░░╚██╔╝░░╚█████╔╝██║╚█████╔╝███████╗
╚═╝╚═╝░░╚══╝░░░╚═╝░░░░╚════╝░╚═╝░╚════╝░╚══════╝

░█████╗░░██████╗░██████╗██╗░██████╗████████╗░█████╗░███╗░░██╗████████╗
██╔══██╗██╔════╝██╔════╝██║██╔════╝╚══██╔══╝██╔══██╗████╗░██║╚══██╔══╝
███████║╚█████╗░╚█████╗░██║╚█████╗░░░░██║░░░███████║██╔██╗██║░░░██║░░░
██╔══██║░╚═══██╗░╚═══██╗██║░╚═══██╗░░░██║░░░██╔══██║██║╚████║░░░██║░░░
██║░░██║██████╔╝██████╔╝██║██████╔╝░░░██║░░░██║░░██║██║░╚███║░░░██║░░░
╚═╝░░╚═╝╚═════╝░╚═════╝░╚═╝╚═════╝░░░░╚═╝░░░╚═╝░░╚═╝╚═╝░░╚══╝░░░╚═╝░░░""")
    print("Example: 'Amazon paid $40000 for 5 GPUs'")
    print("Type 'exit' or 'quit' to end the session.")
    
    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ('exit', 'quit'):
            break
        
        # This is what allows Redis to track distinct conversations
        config = {"configurable": {"thread_id": "user_session_001"}}
        
        # 1. Initialize the State object with user input
        initial_state: AgentState = {
            "messages": [HumanMessage(content=user_input)]
        }
        
        # 2. Execute the entire LangGraph workflow
        final_state = await graph.ainvoke(initial_state, config=config)
        
        # 3. Process and display the final result
        print(final_state["messages"][-1].content)
        
        print("\n")
        
    
# ----------------------------------------RUN----------------------------------------------    
async def run_app():
    graph = await build_graph()
    try:
        await chat_interface(graph)
    finally:
        pass  # No MCP connections to clean up


if __name__ == "__main__":
    try:
        asyncio.run(run_app())
    except KeyboardInterrupt:
        print("\nSession ended.")