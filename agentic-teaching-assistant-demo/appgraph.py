from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from typing import TypedDict, Annotated, Union
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.messages import BaseMessage
import operator
from typing import TypedDict, Annotated, List ,  Any
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.messages import BaseMessage
import operator
from markdown import Markdown
import random
from colorama import Fore
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from langgraph.graph import END, StateGraph
import asyncio
from nodes import init_user_storage,user_exists,load_user_state, update_and_save_user_state, move_to_next_chapter, update_subtopic_status,add_quiz_to_subtopic, build_next_chapter, run_for_first_time_user
from states import Chapter, StudyPlan, Curriculum, User, GlobalState, Status, SubTopic, printmd

"""
## copy GlobalState here for reference 
class GlobalState(TypedDict):
    input: str
    existing_user: bool 
    user: User
    user_id: str  # each user should have a user_id, if it is not specified, it will be randomly generated    
    chat_history: list[BaseMessage]
    next_node_name: str  # name of the current node in the agentic system
    pdf_loc: str  # the location where the pdfs files are uploaded to, default to /workspace/mnt/pdfs/
    save_to: str  # the location to save processed study material, user states and more, default to /workspace/mnt/
    agent_final_output: Union[str, Markdown, None]        
    intermediate_steps: Annotated[list[Union[str, Markdown]], operator.add]
"""

def check_user(data):
    print(Fore.BLUE + "Node = **check_user** > data : ", data ,Fore.RESET)
    user_id=data["user_id"]   
    save_to=data["save_to"] 
    init_user_storage(save_to, user_id)
    user_exist_flag=user_exists(user_id)
    print(Fore.BLUE + " user_exist > ", user_exist_flag )
    data["existing_user"]=user_exist_flag
    
    ## if it is existing user, then load the existing user states and restore from disk
    ## if it is new user then create new curriculum 
    
    
    if not data["intermediate_steps"] :
        data["intermediate_steps"] =[]
    if user_exist_flag:        
        data["next_node_name"]="query_routing"
        # Load existing user state
        user_state = load_user_state(user_id)
        data["user"]=user_state
    else:        
        data["intermediate_steps"].append("first_time_user_setup")
        data["next_node_name"]= "continue"
    return data


def query_routing(data):
    existing_user = data["existing_user"]
    if existing_user :
        u=data["user"]
    

    ## first time user invoke creation of curriculum 
    query=data["input"]
    # llm should classify the query into one of the following 
    ## study_session : study the study materials via chatting with study buddy 
    ## quiz: ready for quiz 
    ## next_chapter : completed this chapter and move on to next chapter 
    ## next_sub_topic : completed this sub_topic and move on to next sub_topic
    ## chitchat : sometimes one needs to relax and chitchat that has nothing to do with studying nor the material 
    ## save_and_quit : if user is too tired to go on and would like to save the current progress and quit , but resume later on.
    
    # Check if intermediate_steps already has a tool to execute
    if data.get("intermediate_steps"):
        # If there are already intermediate steps, continue to execute_tools
        print(Fore.CYAN +"Node = **query_routing** > Found existing intermediate_steps: ", data["intermediate_steps"])
        print("Node = **query_routing** > data : ", data.keys() , Fore.RESET)
        return "continue"
    
    if not data["next_node_name"]:
        output  = random.sample(["study_session","quiz", "next_sub_topic", "next_chapter","chitchat","save_and_quit", "end", "first_time_user_setup"],1)
    else:
        output= data["next_node_name"]
    print(Fore.CYAN +"Node = **query_routing** > output : ", output )    
    print("Node = **query_routing** > data : ", data.keys() , Fore.RESET)
    
    if "study_session" in output:
        data["intermediate_steps"].append("study_session")
        next_node="continue"
    elif "next_chapter" in output:
        data["intermediate_steps"].append("move_to_next_chapter")
        next_node="continue"
    elif "quiz" in output : 
        data["intermediate_steps"].append( "add_quiz_to_subtopic")

        next_node="continue"
    elif "next_sub_topic" in output:
        data["intermediate_steps"].append("move_to_next_subtopic")
        next_node="continue"
    elif "save_and_quit" in output : 
        data["intermediate_steps"].append("save_andupdate_user_states")
        next_node="continue"
    elif "chitchat" in output:
        data["intermediate_steps"].append("chitchat")
        next_node="continue"
    elif "first_time_user_setup" in output:
        data["intermediate_steps"].append("first time user")        
        next_node="end"
    else:
        next_node ="end"
    return next_node


def execute_tools(data):
    existing_user = data["existing_user"]
    if existing_user :
        u=data["user"]
    
    ## first time user invoke creation of curriculum 
    query=data["input"]
    # llm should classify the query into one of the following 
    ## study_session : study the study materials via chatting with study buddy 
    ## quiz: ready for quiz 
    ## next_chapter : completed this chapter and move on to next chapter 
    ## next_sub_topic : completed this sub_topic and move on to next sub_topic
    ## chitchat : sometimes one needs to relax and chitchat that has nothing to do with studying nor the material 
    ## save_and_quit : if user is too tired to go on and would like to save the current progress and quit , but resume later on. 
    tool= data["intermediate_steps"][-1]
    if not data["intermediate_steps"] :
        data["intermediate_steps"] =[]
    print("\n")
    print(Fore.MAGENTA + "Node = **execute_tool** > executing tool : ", tool )
    print("Node = **execute_tool** > data : ", data , Fore.RESET)
    if "study_session" in tool :
        # Load user state if it exists
        if existing_user:
            
            c=u["curriculum"][0]
            active_chapter=c["active_chapter"]        
            response = f"""
            ### Chapter {str(active_chapter.number)}: {active_chapter.name}

            #### 1st Study Topic: {active_chapter.sub_topics[0].sub_topic}

            **Study Material:**

            {active_chapter.sub_topics[0].study_material}"""

            data["agent_final_output"]=response
        else:
            data["agent_final_output"]="User not found. Please set up user first."
    elif "next_chapter" in tool :
        
        data["agent_final_output"]="move to next chapter"
    elif "quiz" in tool  : 
        if existing_user :
            c=u["curriculum"][0]
            active_chapter=c["active_chapter"]
            title=active_chapter.name
            summary=active_chapter.sub_topics[0].sub_topic
            text_chunk=active_chapter.sub_topics[0].study_material
            quizes_ls= get_quiz(title, summary, text_chunk, "")
            active_chapter.sub_topics[0].quizzes=quizes_ls
        data["agent_final_output"]="added quiz , take a look at quiz session"
    elif "next_subtopic" in tool :
        
        data["agent_final_output"]="move to move_to_next_subtopic"
    elif "save_and_quit" in tool : 
        
        data["agent_final_output"]="thanks for talking to me, I'll remember our conversation and your study progress, see you next time !"
    elif "chitchat" in tool :
        
        data["agent_final_output"]="hey what's up?"       
    elif "first_time_user_setup" in tool:
        user_id=data["user_id"]
        preference=data["study_buddy_preference"]
        study_buddy_name=data["study_buddy_name"]
        u: User = {
        "user_id": user_id,
        "study_buddy_preference": preference,
        "study_buddy_name": study_buddy_name,
        "study_buddy_persona": None,
        "curriculum": None,
        }
        
        print(". . . . . . . . . ."*25)
        print("[FIRST_TIME_USER] : populating curriculum for first time user")
        pdf_loc=data["pdf_loc"]
        save_to=data["save_to"]
        # Run for first time user - returns GlobalState
        global_state = asyncio.run(run_for_first_time_user(u, pdf_loc, save_to, preference))
        active_chapter=global_state["user"]["curriculum"][0]["active_chapter"]
        data["agent_final_output"]=f"Let's start with chapter :{str(active_chapter.number)}:{active_chapter.name}"
    else:
        data["agent_final_output"]="completed"
    data["next_node_name"]="end"
    return data


# Define a new graph
workflow = StateGraph(GlobalState)

# Define the two nodes we will cycle between
workflow.add_node("check_user", check_user)
workflow.add_node("execute_tools", execute_tools)

# Set the entrypoint as `agent`
# This means that this node is the first one called
workflow.set_entry_point("check_user")

# We now add a conditional edge
workflow.add_conditional_edges(
    # First, we define the start node. We use `agent`.
    # This means these are the edges taken after the `agent` node is called.
    "check_user",
    # Next, we pass in the function that will determine which node is called next.
    query_routing,
    # Finally we pass in a mapping.
    # The keys are strings, and the values are other nodes.
    # END is a special node marking that the graph should finish.
    # What will happen is we will call `should_continue`, and then the output of that
    # will be matched against the keys in this mapping.
    # Based on which one it matches, that node will then be called.
    {
        # If `tools`, then we call the tool node.
        "continue": "execute_tools",
        # Otherwise we finish.
        "end": END,
    },
)

# We now add a normal edge from `execute_tools` to END.
# This means that after `execute_tools` is called, the graph finishes.
workflow.add_edge("execute_tools", END)

# Finally, we compile it!
# This compiles it into a LangChain Runnable,
# meaning you can use it as you would any other runnable
app = workflow.compile()


if __name__ == "__main__":
    # Test code - only runs when script is executed directly
    inputs={
        "user_id": "babe",     
        "input": "make a curriculum for me", 
        "pdf_loc": "/workspace/mnt/pdfs", 
        "save_to": "/workspace/mnt/",
        "chat_history": [],
        "next_node_name": "",
        "agent_final_output": None,
        "intermediate_steps": ["study_session"]
    }
    #ipython kernel install --user --name=my-conda-env-kernel   # configure Jupyter to use Python kernel
    out=app.invoke(inputs)

    print(out["intermediate_steps"])
    print("--"*10)
    print(Fore.LIGHTGREEN_EX+"type", type(out["agent_final_output"]))
    if out["agent_final_output"]:
        # printmd expects a string with markdown formatting
        
        print(out["agent_final_output"], Fore.RESET)

"""
save_to="/workspace/mnt/"
user_id="babe"
init_user_storage(save_to, user_id)
user_exist_flag=user_exists(user_id)
print(Fore.BLUE + " user_exist > ", user_exist_flag )    
# Load existing user state
user_state = load_user_state(user_id)
print("----"*10)
print(type(user_state), user_state.keys())
print(type(user_state["curriculum"][0]), user_state["curriculum"][0].keys())
c=user_state["curriculum"][0]
print(type(c["active_chapter"]), type(c["study_plan"]), type(c["status"]))
print(" ----> currently active_chapter is = \n ----------------")
active_chapter=c["active_chapter"]
print(f"active_chapter = {active_chapter.number}:{active_chapter.name}")
print("\n SubTopics", '\n'.join([f"{subtopic.number}:{subtopic.sub_topic}" for subtopic in active_chapter.sub_topics]))
print( "\n\n")
print(f"1st study-topic {active_chapter.sub_topics[0].sub_topic} study material - \n", active_chapter.sub_topics[0].study_material)
print("## \n")"""
