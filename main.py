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
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from IPython.display import Image, display
from tools import TransactionDetails, DATABASE_FILE, setup_database, extract_transaction_details, create_invoice, get_ledger_data
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.types import interrupt # For HITL
from langgraph.types import Command
from langchain_core.messages import ToolMessage


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


# System Message
sys_msg = SystemMessage(content=f"""
You are an ERP Assistant for invoice processing.

Tools:
- extract_transaction_details(text): Parse transaction from natural language
- create_invoice(company, amount, product, quantity): Store in database
- get_ledger_data(): Show all transactions

Note: The system will require manual approval before create_invoice executes.

Instructions:
- Extract EXACT details from user text (no invented data)
- Handle currency/numbers correctly
- For "show/display" requests, use get_ledger_data()
- Return clear, user-friendly messages

Examples:
- "Amazon paid $40000 for 5 GPUs" → Extract → Create invoice
- "Show all transactions" → Display ledger
""")


#--------------------------------Build the Graph -----------------------------------------------------
async def build_graph(checkpointer):
    
    builder = StateGraph(AgentState)
    
    llm_with_tools = llm.bind_tools(local_tools)
    
    #------------------------------------AI ASSISTANT---------------------------------------
    async def assistant(state: AgentState):
        
        response = await llm_with_tools.ainvoke([sys_msg] + state["messages"])    
        return{
            "messages": [response],
        }

    # 2. Nodes & Edges
    builder.add_node("assistant", assistant)
    builder.add_node("tools", ToolNode(local_tools))
    builder.add_edge(START, "assistant")
    builder.add_conditional_edges("assistant", tools_condition)
    builder.add_edge("tools", "assistant")
           
    # BREAKPOINT: This stops the graph BEFORE the "tools" node executes.
    app = builder.compile(checkpointer=checkpointer, interrupt_before=["tools"])
    
    # Generate PNG image of the graph
    image_data = app.get_graph().draw_mermaid_png()
    with open("graph.png", "wb") as f:
        f.write(image_data)
        
    return app



#---------------------------------------CHAT INTERFACE-----------------------------------------
async def chat_interface(graph):
    # Initialize database
    await setup_database()
    
    config = {"configurable": {"thread_id": "erp_session_v1"}}
    
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
            # Get current state to see if we are at a breakpoint
            state = await graph.aget_state(config)
            
            # 1. HANDLE BREAKPOINT (HITL)
            if state.next and "tools" in state.next:
                last_msg = state.values["messages"][-1]
                if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                    # We only care about create_invoice for approval
                    invoice_calls = [tc for tc in last_msg.tool_calls if tc["name"] == "create_invoice"]
                    
                    if invoice_calls:
                        print(f"\n[SYSTEM] Action required for invoice creation.")
                        for tc in invoice_calls:
                            print(f"Details: {tc['args']}")
                        
                        choice = input("\nApprove this transaction? (yes/no): ").strip().lower()
                        
                        if choice == "yes":
                            print("Proceeding...")
                            # Stream the tool execution and the subsequent LLM response
                            async for event in graph.astream(None, config=config):
                                for node, data in event.items():
                                    if "messages" in data:
                                        print(f"Assistant: {data['messages'][-1].content}")
                        else:
                            print("Cancelling...")
                            # Tell the LLM the user rejected it so it doesn't try again
                            reject_messages = [
                                ToolMessage(tool_call_id=tc["id"], content="User rejected this.") 
                                for tc in invoice_calls
                            ]
                            await graph.ainvoke({"messages": reject_messages}, config=config)
                        
                        # After handling approval/rejection, jump to the top to check state again
                        continue 

            # 2. HANDLE NORMAL INPUT
            user_input = input("\nYou: ").strip()
            if user_input.lower() in ('exit', 'quit'): break
            if not user_input: continue

            # We use astream to see the transition through nodes
            async for event in graph.astream({"messages": [HumanMessage(content=user_input)]}, config=config):
                for node, data in event.items():
                    if "messages" in data:
                        content = data['messages'][-1].content
                        # Only print if there is actual text to show
                        if content:
                            print(f"Assistant: {content}")
                        # If it's a tool call with no text, let the user know it's "thinking"
                        elif hasattr(data['messages'][-1], "tool_calls") and data['messages'][-1].tool_calls:
                            print(f"[System] Assistant is requesting tool access...")

    
# ----------------------------------------RUN----------------------------------------------    
async def run_app():
    async with AsyncRedisSaver.from_conn_string("redis://localhost:6379") as checkpointer:
        graph = await build_graph(checkpointer)
        await chat_interface(graph)


if __name__ == "__main__":
    try:
        asyncio.run(run_app())
    except KeyboardInterrupt:
        print("\nSession ended.")