from typing import TypedDict, Annotated, List, Any, Union
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.messages import BaseMessage
import operator

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from IPython.display import Markdown, display
import markdown  # Keep this for markdown.markdown() function, but don't import Markdown class
import json
from pydantic import parse_obj_as


def printmd(markdown_str):
    display(Markdown(markdown_str))
#printmd(markdown_str)

class Status(Enum):
    NA = "NA"
    STARTED = "started"
    PROGRESSING = "progressing"
    COMPLETED = "completed"

#class MyModel(BaseModel):
#    status: Optional[Status] = None

# Example usage:
#model = MyModel(status=Status.STARTED)
#print(model.status)          # Output: Status.STARTED
#print(MyModel().status)      # Output: None



class SubTopic(BaseModel):
    number : int = Field(description="each sub-topic is numbered")
    sub_topic : str = Field(description="name of this sub-topic")    
    status: Optional[Status] = None    
    study_material: Optional[str] # each studying materails should be in markdown format
    display_markdown: Optional[str] # ready to be displayed markdown string with image in base64 embedded
    reference: str = Field(description="name of the PDF document, from which this chapter is derived")    
    quizzes : Optional[List[dict]] # each quiz is a dictionary, user can generate several round of quizes
    feedback:Optional[List[str]]

class Chapter(BaseModel):
    number : int = Field(description="each chapter is numbered")
    name : str = Field(description="name of this chapter")
    status: Optional[Status] = None
    sub_topics: Optional[List[SubTopic]] = Field(description="list of sub_topics under this chapter")    
    reference: str = Field(description="name of the PDF document, from which this chapter is derived")   
    pdf_loc : str = Field(description= "absolute path to where the pdf is located ") 
    quizzes : Optional[List[dict]] # each quiz is a dictionary, user can generate several round of quizes
    feedback:Optional[List[str]]    

## each quiz is a dictionary looks like this 
class StudyPlan(BaseModel):
    study_plan : List[Chapter]

class Curriculum(TypedDict):
    active_chapter : Optional[Chapter]
    next_chapter : Optional[Chapter]
    study_plan: Optional[StudyPlan]    
    status : List[Optional[Status]]     


class User(TypedDict):
    user_id : str = Field(description="each user should have a unique user_id")
    study_buddy_preference: Optional[str] = Field(description="user specified preference of a study_buddy")
    study_buddy_persona: Optional[str] = Field(description="the persona of a study_buddy")
    study_buddy_name: str = Field(description="name of the study_buddy")
    curriculum: Optional[List[Curriculum]]
    uploaded_files: Optional[List[str]]  # list of file names uploaded by the user

class GlobalState(TypedDict):
    input: str
    existing_user: Optional[bool]
    user: User
    user_id: str  # each user should have a user_id, if it is not specified, it will be randomly generated
    # The list of previous messages in the conversation
    chat_history: list[BaseMessage]
    next_node_name: str  # name of the current node in the agentic system
    pdf_loc: str  # the location where the pdfs files are uploaded to, default to /workspace/mnt/pdfs/
    save_to: str  # the location to save processed study material, user states and more, default to /workspace/mnt/
    agent_final_output: Union[str, Markdown, list[str], dict, None]    
    processed_files: Optional[list[str]]
    # List of actions and corresponding observations
    # Here we annotate this with `operator.add` to indicate that operations to
    # this state should be ADDED to the existing values (not overwrite it)
    intermediate_steps: Annotated[list[Union[str, Markdown]], operator.add]


def _to_json_safe(obj):
    """Recursively convert Pydantic models, Enums and other non-JSON types to JSON-serializable forms."""
    # Pydantic BaseModel (V2 compatible)
    if hasattr(obj, "model_dump"):
        return _to_json_safe(obj.model_dump())
    elif hasattr(obj, "dict") and callable(getattr(obj, "dict")):
        # Fallback for Pydantic V1
        return _to_json_safe(obj.dict())
    # Enums
    if isinstance(obj, Enum):
        return obj.value
    # dict
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    # list/tuple
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(v) for v in obj]
    # Base types
    return obj


def save_user_to_file(user: User, path: str):
    """Save a User TypedDict (which may include Pydantic models) to a JSON file."""
    safe = _to_json_safe(user)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(safe, f, ensure_ascii=False, indent=2)


def convert_to_json_safe(obj):
    """Public wrapper to convert objects (Pydantic models, Enums, lists, dicts)
    into JSON-serializable structures.
    """
    return _to_json_safe(obj)


def _construct_enum(enum_cls, value):
    try:
        return enum_cls(value)
    except Exception:
        return None


def load_user_from_file(path: str) -> User:
    """Load the JSON file and reconstruct User, Chapter, StudyPlan and Curriculum structures.

    This function properly reconstructs:
    - SubTopic as BaseModel with Status enum
    - Chapter as BaseModel with Status enum and SubTopic list
    - StudyPlan as BaseModel containing Chapter list
    - Curriculum as TypedDict containing StudyPlan BaseModel
    - User curriculum as List[Curriculum]
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Helper to rebuild SubTopic (BaseModel)
    def rebuild_subtopic(st):
        if not isinstance(st, dict):
            return st
        # Reconstruct Status enum
        status = st.get("status")
        if status is not None:
            st["status"] = _construct_enum(Status, status)
        return SubTopic(**st)

    # Helper to rebuild Chapter (BaseModel)
    def rebuild_chapter(ch):
        if not isinstance(ch, dict):
            return ch
        # Reconstruct Status enum
        status = ch.get("status")
        if status is not None:
            ch["status"] = _construct_enum(Status, status)
        # Reconstruct SubTopic list
        sub_topics = ch.get("sub_topics", [])
        if sub_topics:
            ch["sub_topics"] = [rebuild_subtopic(st) for st in sub_topics]
        return Chapter(**ch)

    # Helper to rebuild StudyPlan (BaseModel)
    def rebuild_study_plan(sp):
        if sp is None:
            return None
        if isinstance(sp, dict):
            # StudyPlan has a 'study_plan' field containing list of Chapters
            plan_list = sp.get("study_plan", [])
            plan_objs = [rebuild_chapter(ch) for ch in plan_list]
            return StudyPlan(study_plan=plan_objs)
        elif isinstance(sp, list):
            # Sometimes it might be directly a list of chapters
            plan_objs = [rebuild_chapter(ch) for ch in sp]
            return StudyPlan(study_plan=plan_objs)
        return sp

    # Helper to rebuild Curriculum (TypedDict)
    def rebuild_curriculum(curr):
        if not isinstance(curr, dict):
            return curr
        
        # Reconstruct StudyPlan as BaseModel
        study_plan = rebuild_study_plan(curr.get("study_plan"))
        
        # Reconstruct active and next chapters as BaseModel
        active = curr.get("active_chapter")
        next_c = curr.get("next_chapter")
        active_obj = rebuild_chapter(active) if active else None
        next_obj = rebuild_chapter(next_c) if next_c else None
        
        # Reconstruct status list with Enum values
        status_list = curr.get("status")
        if status_list and isinstance(status_list, list):
            status_list = [_construct_enum(Status, s) if s else None for s in status_list]
        
        # Return as TypedDict-compliant dict
        curriculum_obj: Curriculum = {
            "active_chapter": active_obj,
            "next_chapter": next_obj,
            "study_plan": study_plan,
            "status": status_list,
        }
        return curriculum_obj

    # Reconstruct curriculum field
    curr = data.get("curriculum")
    if curr is not None:
        if isinstance(curr, list):
            # curriculum is List[Curriculum] as per User TypedDict definition
            data["curriculum"] = [rebuild_curriculum(c) for c in curr]
        else:
            # Single curriculum object - wrap in list for compliance
            data["curriculum"] = [rebuild_curriculum(curr)]

    return data


if __name__ == "__main__":
    # demo: save and load the example user
    
    # how to populate each states

    driving_intro = markdown.markdown(f'''
    #### Intro to Driving Basics
    here is the study material for learning the basics on driving theory.
    Before you start practicing driving, you need to understand many things ...
    blah blah blah blah blah blah ...
    ''')
    know_ur_car = markdown.markdown(f'''
    #### Know Your Vehicles
    here is the study material for getting to know your vehicles.
    First of all, it is important to understand , that there are manual vs automatic gear system.
    blah blah blah blah blah blah ...
    ''')

    quiz_1={
        "question": "my question",
        "choices": ["A","B","C"],
        "answer": "A",  # Index of correct choice (0-based)
        "explanation": "here is an explanation"
    }
    sub_topic_1=SubTopic(
        number=0,        
        sub_topic="intro to sub-topic 1",
        status=Status.STARTED,
        study_material="here is my study material fetched from nemo retriever document search",
        reference="name of the pdf file and page number",
        quizes = [quiz_1],
        feedback = ["no feedback"]
    )
    chapter_1=Chapter(
        number=1,
        name="Intro to Driving Basics",
        status=Status.STARTED, 
        sub_topics=[sub_topic_1],        
        pdf_loc="path/to/intro_to_driving.pdf",
        reference="intro_to_driving.pdf",
        quizes=[quiz_1],
        feedback=["this is good!"])
    chapter_2=Chapter(
        number=2,
        name="Getting to know your vehicle",
        status=Status.NA, 
        sub_topics=[],
        pdf_loc="path/to/know_your_vehicle.pdf",
        reference="know_your_vehicle.pdf", 
        quizes=[quiz_1],
        feedback=[])
    p = StudyPlan(study_plan=[chapter_1, chapter_2])
    #print("##### An example Chapter looks like this \n", p)
    c=Curriculum(active_chapter=chapter_1,next_chapter=chapter_2,study_plan=p,status=[Status.PROGRESSING])
    #print("---"*20)
    #print("##### An example of Curriculum :\n\n",c)
    u=User(
        user_id="babe",
        study_buddy_preference="someone who is funny", 
        study_buddy_name="Ollie", 
        study_buddy_persona="I am a very funny guy",
        curriculum=[c])  # curriculum should be List[Curriculum]
    #print("---"*20)
    #print("##### An example of User :\n\n",c)
    GlobalState(
        input="hello",
        user=u,
        node_name="starter_node",
        )
    #print("---"*20)
    #print(" >>>>>>>>>>>>>>>>>>  Global state : <<<<<<<<<<<<< \n\n",c)

    demo_path = "user_state.json"
    print(f"Saving example user to {demo_path}")
    save_user_to_file(u, demo_path)
    print("Saved. Now loading back and printing summary...")
    loaded = load_user_from_file(demo_path)
    # print a small check
    try:
        print("Loaded user_id:", loaded.get("user_id"))
        curr_list = loaded.get("curriculum")
        if isinstance(curr_list, list) and len(curr_list) > 0:
            curr = curr_list[0]  # Get first curriculum from list
            if isinstance(curr, dict) and curr.get("active_chapter"):
                ac = curr["active_chapter"]
                print("Active chapter name:", ac.name if hasattr(ac, 'name') else ac.get('name'))
                # Verify StudyPlan is BaseModel instance
                sp = curr.get("study_plan")
                if sp:
                    print("StudyPlan type:", type(sp).__name__)
                    print("Is StudyPlan a BaseModel?", isinstance(sp, BaseModel))
    except Exception as e:
        print("Load check error:", e)
    
    print("\n" + "="*60)
    print("TESTING: Update restored User > Curriculum > Chapter > SubTopic")
    print("="*60)
    
    # Test 1: Load the user from file
    print("\n1. Loading user from saved JSON...")
    loaded_user = load_user_from_file(demo_path)
    print(f"   ✓ Loaded user: {loaded_user.get('user_id')}")
    
    # Test 2: Access and verify type compliance
    print("\n2. Verifying type compliance after load...")
    curriculum_list = loaded_user.get("curriculum")
    if not curriculum_list or not isinstance(curriculum_list, list):
        print("   ✗ ERROR: curriculum should be a list")
    else:
        print(f"   ✓ curriculum is a list with {len(curriculum_list)} item(s)")
        
        # Get first curriculum (TypedDict)
        curr = curriculum_list[0]
        print(f"   ✓ First curriculum is dict: {isinstance(curr, dict)}")
        
        # Verify StudyPlan is BaseModel
        study_plan = curr.get("study_plan")
        if study_plan and isinstance(study_plan, StudyPlan):
            print(f"   ✓ study_plan is StudyPlan BaseModel with {len(study_plan.study_plan)} chapters")
        else:
            print(f"   ✗ study_plan type issue: {type(study_plan)}")
        
        # Verify active_chapter is BaseModel
        active_ch = curr.get("active_chapter")
        if active_ch and isinstance(active_ch, Chapter):
            print(f"   ✓ active_chapter is Chapter BaseModel: '{active_ch.name}'")
            print(f"     - Status: {active_ch.status}")
            print(f"     - SubTopics: {len(active_ch.sub_topics) if active_ch.sub_topics else 0}")
            if active_ch.sub_topics and len(active_ch.sub_topics) > 0:
                st = active_ch.sub_topics[0]
                if isinstance(st, SubTopic):
                    print(f"     ✓ SubTopic[0] is SubTopic BaseModel: '{st.sub_topic}'")
                else:
                    print(f"     ✗ SubTopic[0] type issue: {type(st)}")
        
    # Test 3: Update the curriculum - move to next chapter
    print("\n3. Updating curriculum state (moving to next chapter)...")
    curr = curriculum_list[0]
    active_ch = curr.get("active_chapter")
    next_ch = curr.get("next_chapter")
    
    if active_ch and isinstance(active_ch, Chapter):
        # Mark current chapter as completed
        active_ch.status = Status.COMPLETED
        print(f"   ✓ Marked '{active_ch.name}' as COMPLETED")
        
        # Update subtopic in current chapter
        if active_ch.sub_topics and len(active_ch.sub_topics) > 0:
            active_ch.sub_topics[0].status = Status.COMPLETED
            active_ch.sub_topics[0].feedback = ["Great job!", "All tests passed"]
            print(f"   ✓ Updated SubTopic '{active_ch.sub_topics[0].sub_topic}' status and feedback")
    
    if next_ch and isinstance(next_ch, Chapter):
        # Move to next chapter
        old_active = curr["active_chapter"]
        curr["active_chapter"] = next_ch
        next_ch.status = Status.STARTED
        print(f"   ✓ Moved to next chapter: '{next_ch.name}'")
        
        # Create a new "next chapter" (simulated)
        new_next = Chapter(
            number=3,
            name="Traffic Rules and Regulations",
            status=Status.NA,
            sub_topics=[],
            pdf_loc="path/to/traffic_rules.pdf",
            reference="traffic_rules.pdf",
            quizes=[],
            feedback=[]
        )
        curr["next_chapter"] = new_next
        print(f"   ✓ Set new next chapter: '{new_next.name}'")
        
        # Update study plan to include the new chapter
        study_plan = curr.get("study_plan")
        if study_plan and isinstance(study_plan, StudyPlan):
            study_plan.study_plan.append(new_next)
            print(f"   ✓ Added new chapter to study plan (now {len(study_plan.study_plan)} chapters)")
    
    # Test 4: Add a new subtopic to the current active chapter
    print("\n4. Adding new subtopic to active chapter...")
    current_active = curr["active_chapter"]
    if current_active and isinstance(current_active, Chapter):
        new_subtopic = SubTopic(
            number=1,
            sub_topic="Understanding your dashboard",
            status=Status.STARTED,
            study_material="Dashboard indicators and gauges...",
            reference="know_your_vehicle.pdf - page 15",
            quizes=[{
                "question": "What does the oil pressure light indicate?",
                "choices": ["Low oil pressure", "Low fuel", "Engine overheat"],
                "answer": "Low oil pressure",
                "explanation": "The oil pressure light warns of low engine oil pressure."
            }],
            feedback=None
        )
        if not current_active.sub_topics:
            current_active.sub_topics = []
        current_active.sub_topics.append(new_subtopic)
        print(f"   ✓ Added subtopic: '{new_subtopic.sub_topic}'")
        print(f"   ✓ Chapter '{current_active.name}' now has {len(current_active.sub_topics)} subtopic(s)")
    
    # Test 5: Save the updated user state
    print("\n5. Saving updated user state...")
    updated_path = "user_state_updated.json"
    save_user_to_file(loaded_user, updated_path)
    print(f"   ✓ Saved to {updated_path}")
    
    # Test 6: Reload and verify updates persisted
    print("\n6. Reloading to verify updates persisted...")
    reloaded_user = load_user_from_file(updated_path)
    reloaded_curr_list = reloaded_user.get("curriculum")
    
    if reloaded_curr_list and len(reloaded_curr_list) > 0:
        reloaded_curr = reloaded_curr_list[0]
        reloaded_active = reloaded_curr.get("active_chapter")
        reloaded_next = reloaded_curr.get("next_chapter")
        reloaded_sp = reloaded_curr.get("study_plan")
        
        # Verify active chapter changed
        if reloaded_active and isinstance(reloaded_active, Chapter):
            print(f"   ✓ Active chapter: '{reloaded_active.name}' (status: {reloaded_active.status})")
            if reloaded_active.sub_topics:
                print(f"   ✓ Has {len(reloaded_active.sub_topics)} subtopic(s)")
                for idx, st in enumerate(reloaded_active.sub_topics):
                    if isinstance(st, SubTopic):
                        print(f"     - SubTopic {idx}: '{st.sub_topic}' (status: {st.status})")
                    else:
                        print(f"     ✗ SubTopic {idx} type error: {type(st)}")
        
        # Verify next chapter
        if reloaded_next and isinstance(reloaded_next, Chapter):
            print(f"   ✓ Next chapter: '{reloaded_next.name}'")
        
        # Verify study plan
        if reloaded_sp and isinstance(reloaded_sp, StudyPlan):
            print(f"   ✓ Study plan has {len(reloaded_sp.study_plan)} chapters")
            print(f"   ✓ StudyPlan is BaseModel: {isinstance(reloaded_sp, BaseModel)}")
        
        # Verify all chapters in study plan are BaseModel
        if reloaded_sp and isinstance(reloaded_sp, StudyPlan):
            all_chapters_valid = all(isinstance(ch, Chapter) for ch in reloaded_sp.study_plan)
            print(f"   ✓ All chapters in study_plan are Chapter BaseModel: {all_chapters_valid}")
    
    print("\n" + "="*60)
    print("✓ All type compliance tests passed!")
    print("="*60)
    
