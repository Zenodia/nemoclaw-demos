from langchain_core.prompts import ChatPromptTemplate
import os, sys 
import json
from langchain_core.messages import SystemMessage, HumanMessage
from common.debug import debug_print, get_debug_logger
from llm import create_llm

logger = get_debug_logger(__name__)

llm = create_llm("query_decomposition")

query_decompostion_prompt = """<System>

CRITICAL: You are a JSON-ONLY Query Decomposition Agent. You MUST output ONLY valid JSON - no text, no explanations, no greetings.

Your role: Analyze user queries and output a JSON plan for which tools to use.

IMPORTANT RULES:
1. OUTPUT FORMAT: You MUST respond with ONLY a JSON array. No text before or after.
2. DO NOT answer the user's question. DO NOT generate a response. ONLY output a tool plan.
3. If you output anything other than JSON, the system will fail.

</System>

<Available Tools>

IMPORTANT: These are the ONLY tools available. You CANNOT use any other tools not listed here.
If a query requires capabilities beyond these tools, you MUST use the "none" tool.

You have access to the following tools:

1. chitchat - For casual conversation, greetings, small talk, and general social interactions, this tool will track conversational history
2. summary - use this tool to integrate, summarize and combine information from multiple sources
3. book_calendar - For scheduling, booking appointments, managing calendar events (ONLY for time management, NOT for ordering services or products)
4. minigame - For interactive games, quizzes, or fun activities
5. study_material - For educational content, learning resources, study guides
6. arxiv - for search for arxiv for research papers 
7. youtube_search - For finding YouTube video tutorials, educational videos, and visual learning content related to the study topic
8. final_response - For directly responding to the user (used as the final step to wrap and deliver results)
9. none - Use this when the query cannot be fulfilled because required tools/capabilities are not available


Example capabilities that DO NOT exist:
- No email/messaging tools
- No weather API tools (no weather forecasting)
- No food ordering/e-commerce/delivery tools
- No social media tools
- No payment/financial transaction tools
- No phone/calling tools
- No image generation or manipulation tools
- No file system access tools
- No general web search (except for youtube_search which is available for video content)

</Available Tools>

</Available Tools>

<Instructions>

0. FIRST - Validate Tool Availability (CRITICAL):
   - BEFORE analyzing the query, check if ALL required capabilities exist in the available tools
   - NEVER invent, hallucinate, or assume tools that are not in the Available Tools list
   - If the query requires ANY capability not provided by the available tools, IMMEDIATELY respond with:
     * "multi_steps": false
     * "tool_name": "none"
     * "rationale": Clearly explain which capabilities are missing and why the query cannot be fulfilled
   - Examples of queries that CANNOT be fulfilled:
     * Ordering food/products (no e-commerce or food delivery tools)
     * Checking weather (no weather API tool)
     * Sending emails/messages (no communication tools)
     * Making phone calls (no telephony tools)
     * Accessing social media (no social media tools)
     * Financial transactions (no payment tools)

1. Analyze Query Complexity
   - Only proceed if all required tools are available
   - Determine if the query is ATOMIC (requires 1-2 tools) or COMPLEX (requires multiple tools/steps)
   - ATOMIC queries: greetings, question where a single tool call can fulfill, a single-step task
   - COMPLEX queries: require breaking down the query to multiple step/sub-tasks, queries requiring information from multiple sources, or tasks with dependencies

2. For ATOMIC Queries:
   - Set "multi_steps" to false   
   - Identify the primary tool needed (e.g., chitchat, book_calendar, etc.)
   - Follow below logic to set the tool_name in response:
      if no tools are needed, then direct response to the user with the tool_name set to final_response
      else-if a tool is used, however the result of the tool call can directly be used as response to the user, then count this as atomic query and skip final_response step and response the result of the tool call direclty to the user
      else if a tool is needed to be called, however the tool does not exist or is not available, then directly respond to the user with tool_name set to none and rationale explaining why it is not possible to construct a plan    
   - Provide clear rationale for each step

3. For COMPLEX Queries (multiple tools needed):   
   - Always check if the user query can be fulfilled by the avialable tools before constructing the plan, if not set the tool_name to none and rationale explaining why it is not possible to construct a valid plan
   - Set "multi_steps" to true   
   - Decompose the query into atomic steps
   - Each step must use EXACTLY ONE tool
   - Each step should be independent and self-contained   
   - Order steps logically based on dependencies, if a step depends on the result of the previous step, then the previous step should be executed first
   - CRITICAL: "final_response" should ONLY appear as the VERY LAST STEP in the plan
   - NEVER use "final_response" in intermediate steps - use appropriate tools like "study_material", "summary", "arxiv", etc. instead
   - The final step/last step must ALWAYS be "final_response" with step_nr equal to the total number of steps
   - If a valid plan cannot be constructed, set tool_name to "none" with rationale explaining why

</Instructions>

<Output Format>

You MUST respond with ONLY valid JSON as a LIST containing ONE object in the following format:

[
  {{
    "multi_steps": true/false,    
    "output_steps": [
      {{
        "step_nr": 1,        
        "tool_name": "tool_name_here",
        "rationale": "clear explanation of why this tool is used for this step"
      }}
    ]
  }}
]

</Output Format>

<Examples>

Example 1 - Atomic Query - Greeting:
User: "hi", "hello", "how are you?"
Response:
[
  {{
    "multi_steps": false,    
    "output_steps": [
      {{
        "step_nr": 1,        
        "tool_name": "final_response",
        "rationale": "user's intention is for generic greeting, does not require conversational tracking, therefore, chitchat tool is not needed"
      }}
    ]
  }}
]

Example 2 - Atomic Query - Single Tool usage:
User: "book a focus time at 3pm tomorrow for 2 hours for me to study"
Response:
[
  {{
    "multi_steps": false,    
    "output_steps": [
      {{
        "step_nr": 1,        
        "tool_name": "book_calendar",
        "rationale": "use book_calendar tool to book a calendar event, booked event will be a downloadable ics file no need for additional tools to be called"
      }}
    ]
  }}
]

Example 3 - Complex Query - Multiple Steps (2 tools):
User: "summarize the most important concept I must learn learn with respect to the study material and then search for a youtube video tutorial explaining the main concept"
Response:
[
  {{
    "multi_steps": true,
    "output_steps": [
      {{
        "step_nr": 1,        
        "tool_name": "study_material",
        "rationale": "need to first digest the study material in order to extract one most important concept"
      }},
      {{
        "step_nr": 2,        
        "tool_name": "youtube_search",
        "rationale": "need to search for an appropriate youtube video tutorial explaining the main concept"
      }},
      {{
        "step_nr": 3,        
        "tool_name": "summary",
        "rationale": "need to summarize the study material and the youtube video tutorial into a single coherent explanation"
      }},
      {{
        "step_nr": 4,        
        "tool_name": "final_response",
        "rationale": "Ready to respond to the user with the summary of the main concept with the found youtube video link attached"
      }}
    ]
  }}
]

Example 3b - Complex Query - Multiple Steps (3 tools with calendar):
User: "summarize one of the most important concepts I must learn with respect to the study material, then search for a youtube video tutorial explaining the main concept, finally book myself for 2 hrs on Friday this week to focus on studying"
Response:
[
  {{
    "multi_steps": true,
    "output_steps": [
      {{
        "step_nr": 1,        
        "tool_name": "study_material",
        "rationale": "extract the most important concept from the study material that the user should focus on"
      }},
      {{
        "step_nr": 2,        
        "tool_name": "youtube_search",
        "rationale": "search for a youtube video tutorial that explains the extracted main concept"
      }},
      {{
        "step_nr": 3,        
        "tool_name": "book_calendar",
        "rationale": "book a 2-hour study session on Friday this week for the user to focus on studying"
      }},
      {{
        "step_nr": 4,        
        "tool_name": "final_response",
        "rationale": "deliver comprehensive response with the main concept summary, the youtube video link, and confirmation of the booked calendar event"
      }}
    ]
  }}
]

Example 3c - Complex Query - Two Tools (topic query + video):
User: "Tell me about Sweden and find a YouTube tutorial about it"
Response:
[
  {{
    "multi_steps": true,
    "output_steps": [
      {{
        "step_nr": 1,        
        "tool_name": "study_material",
        "rationale": "provide information about Sweden based on available knowledge"
      }},
      {{
        "step_nr": 2,        
        "tool_name": "youtube_search",
        "rationale": "search for a youtube tutorial about Sweden"
      }},
      {{
        "step_nr": 3,        
        "tool_name": "final_response",
        "rationale": "deliver the information about Sweden along with the embedded youtube video"
      }}
    ]
  }}
]

Example 4 - INCORRECT Multi-Step (BAD - DO NOT DO THIS):
User: "find research papers on transformers and explain them to me, then find a video"
WRONG Response:
[
  {{
    "multi_steps": true,
    "output_steps": [
      {{
        "step_nr": 1,
        "tool_name": "arxiv",
        "rationale": "search for papers"
      }},
      {{
        "step_nr": 2,
        "tool_name": "final_response",  ❌ WRONG - final_response used too early!
        "rationale": "explain papers to user"
      }},
      {{
        "step_nr": 3,
        "tool_name": "youtube_search",
        "rationale": "find video"
      }}
    ]
  }}
]

CORRECT Response:
[
  {{
    "multi_steps": true,
    "output_steps": [
      {{
        "step_nr": 1,
        "tool_name": "arxiv",
        "rationale": "search for research papers on transformers"
      }},
      {{
        "step_nr": 2,
        "tool_name": "study_material",  ✓ CORRECT - use appropriate tool for processing
        "rationale": "analyze and extract key concepts from the papers"
      }},
      {{
        "step_nr": 3,
        "tool_name": "youtube_search",
        "rationale": "find educational video about transformers"
      }},
      {{
        "step_nr": 4,
        "tool_name": "final_response",  ✓ CORRECT - final_response only at the end
        "rationale": "deliver comprehensive explanation with papers and video to user"
      }}
    ]
  }}
]

Example 5 - Query Cannot Be Fulfilled - Missing Required Tools:
User: "order me a pizza for delivery and check the weather forecast for tomorrow"
Response:
[
  {{
    "multi_steps": false,
    "output_steps": [
      {{
        "step_nr": 1,
        "tool_name": "none",
        "rationale": "Cannot fulfill this request. The query requires two capabilities that are not available: (1) food ordering/delivery service - no e-commerce or food delivery tool exists, and (2) weather forecasting - no weather API tool exists. The available tools are focused on educational assistance (study materials, quizzes, calendar scheduling, research papers) and cannot handle food ordering or weather information."
      }}
    ]
  }}
]

Example 6 - Query Cannot Be Fulfilled - Wrong Tool Usage:
User: "send an email to my professor about my assignment"
WRONG Response (DO NOT DO THIS):
[
  {{
    "multi_steps": false,
    "output_steps": [
      {{
        "step_nr": 1,
        "tool_name": "chitchat",  ❌ WRONG - chitchat is not for sending emails
        "rationale": "use chitchat to send email"
      }}
    ]
  }}
]

CORRECT Response:
[
  {{
    "multi_steps": false,
    "output_steps": [
      {{
        "step_nr": 1,
        "tool_name": "none",  ✓ CORRECT - no email tool exists
        "rationale": "Cannot fulfill this request. The query requires email sending capability, but no email or messaging tool is available in the current toolset. The available tools are limited to educational content (study materials, quizzes), calendar management, research paper searches, and conversational interactions."
      }}
    ]
  }}
]

</Examples>

<Constraints>

ABSOLUTELY CRITICAL - JSON OUTPUT ONLY:
- Your response MUST start with [ and end with ]
- Your response MUST be valid JSON - nothing else
- DO NOT write any text, greetings, or explanations
- DO NOT answer the user's question - only output the plan
- If you output ANYTHING other than JSON, the system will BREAK

JSON FORMAT RULES:
- Response must be a JSON array wrapped in [ ]
- Each step must have exactly ONE tool
- Always include "step_nr" starting from 1
- Always include "rationale" explaining why that tool is chosen
- Make each step atomic

CRITICAL RULES FOR "none" TOOL:
- NEVER invent, hallucinate, or use tools that are not explicitly listed
- If the query requires ANY capability not available, use "none" as tool_name
- When using "none", set "multi_steps" to false
- Provide detailed rationale explaining what capabilities are missing

CRITICAL RULES FOR "final_response":
- For multi_steps=true: "final_response" MUST ONLY be the LAST step
- NEVER use "final_response" in intermediate steps
- When users ask for "video", "youtube", "tutorial", use "youtube_search" tool
- "final_response" is ONLY for delivering the final answer after ALL processing

</Constraints>
<Current_Context_Info>

- Overall learning topic: {chapter_name}
- Current subtopic: {sub_topic}
- Study material: {study_material}
- Related quizzes: {stringified}
{memory_section}{history_section}
### User Query
{user_input}
</Current_Context_Info>"""

def query_decomposition_call(user_input: str, chapter_name: str = "", sub_topic: str = "", study_material: str = "", stringified: str = "", memory_section: str = "", history_section: str = ""):
    """
    Call the LLM with the query and system prompt to decompose the query into steps.
    
    Args:
        user_input: User query string
        chapter_name: Name of the current chapter/topic
        sub_topic: Current subtopic
        study_material: Study material text content
        stringified: JSON stringified quizzes
        memory_section: Memory context section
        history_section: Conversation history section
    
    Returns:
        Parsed JSON response as a list containing the decomposition dictionary
    """
    debug_print(f"[DEBUG] query_decomposition_call INPUT: '{user_input}'", flush=True)
    debug_print(f"[DEBUG] query_decomposition_call INPUT length: {len(user_input)}", flush=True)
    
    # Format the system prompt with actual values
    formatted_prompt = query_decompostion_prompt.format(
        chapter_name=chapter_name if chapter_name else "N/A",
        sub_topic=sub_topic if sub_topic else "N/A",
        study_material=study_material if study_material else "N/A",
        stringified=stringified if stringified else "N/A",
        memory_section=memory_section if memory_section else "",
        history_section=history_section if history_section else "",
        user_input=user_input
    )
    
    messages = [
        SystemMessage(content=formatted_prompt),
        HumanMessage(content=user_input)
    ]
    
    response = llm.invoke(messages)
    raw_content = response.content.strip()
    
    try:
        # Try to parse the response as JSON (should be a list)
        parsed_response = json.loads(raw_content)
        
        # Ensure it's a list
        if not isinstance(parsed_response, list):
            # If it's a dict, wrap it in a list
            parsed_response = [parsed_response]
        
        return parsed_response
    except json.JSONDecodeError as e:
        # Try to extract JSON from the response if LLM added surrounding text
        import re
        json_match = re.search(r'\[[\s\S]*\]', raw_content)
        if json_match:
            try:
                extracted_json = json_match.group(0)
                parsed_response = json.loads(extracted_json)
                if not isinstance(parsed_response, list):
                    parsed_response = [parsed_response]
                debug_print("[DEBUG] Extracted JSON from mixed response successfully")
                return parsed_response
            except json.JSONDecodeError:
                pass  # Fall through to error handling
        
        logger.warning("Error parsing query decomposition JSON response: %s", e)
        debug_print(f"Raw response: {raw_content[:500]}...")  # Truncate for logging
        
        # Fallback: Try to detect what the user wants and route appropriately
        user_lower = user_input.lower()
        fallback_tool = "final_response"
        fallback_multi = False
        
        # Simple heuristics for fallback routing
        if any(kw in user_lower for kw in ["youtube", "video", "tutorial", "watch"]):
            if any(kw in user_lower for kw in ["tell me", "explain", "what is", "about"]):
                # User wants info + video
                fallback_multi = True
                return [
                    {
                        "multi_steps": True,
                        "output_steps": [
                            {"step_nr": 1, "tool_name": "study_material", "rationale": "Provide information from study material"},
                            {"step_nr": 2, "tool_name": "youtube_search", "rationale": "Find relevant YouTube video"},
                            {"step_nr": 3, "tool_name": "final_response", "rationale": "Deliver combined response"}
                        ]
                    }
                ]
            else:
                fallback_tool = "youtube_search"
        elif any(kw in user_lower for kw in ["schedule", "book", "calendar", "appointment"]):
            fallback_tool = "book_calendar"
        elif any(kw in user_lower for kw in ["game", "play", "quiz", "fun"]):
            fallback_tool = "minigame"
        elif any(kw in user_lower for kw in ["research", "paper", "arxiv"]):
            fallback_tool = "arxiv"
        
        return [
            {
                "multi_steps": fallback_multi,
                "output_steps": [
                    {
                        "step_nr": 1,
                        "tool_name": fallback_tool,
                        "rationale": f"Fallback routing (JSON parse failed): detected '{fallback_tool}' intent"
                    }
                ]
            }
        ]


if __name__ == "__main__":
    # Test queries demonstrating different complexity levels with realistic study contexts
    test_cases = [
        {
            "query": "hello! how are you?",
            "chapter": "Introduction to Python Programming",
            "subtopic": "Variables and Data Types",
            "study_material": "In Python, a variable is a container for storing data values. Python has no command for declaring a variable. A variable is created the moment you first assign a value to it. Variables can store different types of data: integers (whole numbers), floats (decimal numbers), strings (text), and booleans (True/False).",
            "quizzes": [{"question": "What is a variable in Python?", "answer": "A container for storing data values"}],
            "description": "Simple chitchat greeting"
        },
        {
            "query": "what is a variable and how do I use it?",
            "chapter": "Introduction to Python Programming",
            "subtopic": "Variables and Data Types",
            "study_material": "In Python, a variable is a container for storing data values. You create a variable by assigning a value to it using the = operator. For example: x = 5 creates a variable named 'x' with value 5. You can change the value later: x = 10. Variables can store integers, floats, strings, and booleans.",
            "quizzes": [{"question": "How do you create a variable in Python?", "answer": "By assigning a value using the = operator"}],
            "description": "Simple study material query about current subtopic"
        },
        {
            "query": "schedule a study session tomorrow at 3pm for 2 hours",
            "chapter": "Machine Learning Fundamentals",
            "subtopic": "Supervised Learning",
            "study_material": "Supervised learning is a type of machine learning where the algorithm learns from labeled training data. The model learns to map inputs to outputs based on example input-output pairs. Common supervised learning tasks include classification (predicting categories) and regression (predicting continuous values).",
            "quizzes": [{"question": "What is supervised learning?", "answer": "Learning from labeled training data"}],
            "description": "Calendar booking request"
        },
        {
            "query": "I want to take a break, let's play a game!",
            "chapter": "Data Structures and Algorithms",
            "subtopic": "Binary Search Trees",
            "study_material": "A Binary Search Tree (BST) is a tree data structure where each node has at most two children. The left subtree contains nodes with values less than the parent node, and the right subtree contains nodes with values greater than the parent node. This property enables efficient searching, insertion, and deletion operations with O(log n) time complexity in balanced trees.",
            "quizzes": [{"question": "What is the key property of a BST?", "answer": "Left child < parent < right child"}],
            "description": "Minigame/break request"
        },
        {
            "query": "can you find me a YouTube video tutorial about neural networks?",
            "chapter": "Deep Learning Basics",
            "subtopic": "Neural Network Architecture",
            "study_material": "A neural network is composed of layers of interconnected nodes (neurons). Each connection has a weight, and each neuron applies an activation function to its inputs. The basic architecture includes: Input Layer (receives data), Hidden Layers (process data through weighted connections), and Output Layer (produces predictions).",
            "quizzes": [{"question": "What are the three main layers in a neural network?", "answer": "Input, Hidden, and Output layers"}],
            "description": "External resource request - web search for videos"
        },
        {
            "query": "explain the first quiz question to me",
            "chapter": "Quantum Computing",
            "subtopic": "Qubits and Superposition",
            "study_material": "A qubit is the basic unit of quantum information. Unlike classical bits that are either 0 or 1, qubits can exist in a superposition of both states simultaneously. This property allows quantum computers to process multiple possibilities at once, giving them potential advantages for certain types of calculations.",
            "quizzes": [
                {"question": "What is superposition in quantum computing?", "answer": "The ability of a qubit to be in multiple states simultaneously"},
                {"question": "How is a qubit different from a classical bit?", "answer": "Qubits can exist in superposition, classical bits are either 0 or 1"}
            ],
            "description": "Study material query about quiz"
        },
        {
            "query": "I don't understand the second quiz question, can you help me understand it better and then show me a video about it?",
            "chapter": "Quantum Computing",
            "subtopic": "Qubits and Superposition",
            "study_material": "A qubit is the basic unit of quantum information. Unlike classical bits that are either 0 or 1, qubits can exist in a superposition of both states simultaneously. This allows quantum computers to explore multiple solutions at once. When measured, a qubit collapses to either 0 or 1, but before measurement, it exists in both states with certain probabilities.",
            "quizzes": [
                {"question": "What is superposition in quantum computing?", "answer": "The ability of a qubit to be in multiple states simultaneously"},
                {"question": "How is a qubit different from a classical bit?", "answer": "Qubits can exist in superposition, classical bits are either 0 or 1"}
            ],
            "description": "Complex multi-step: study_material explanation + web_search for video + final_response"
        },
        {
            "query": "find me research papers on transformer architectures from arxiv and explain the key concepts to me, also find a youtube video walk through on autoregressive models",
            "chapter": "Natural Language Processing",
            "subtopic": "Transformer Models",
            "study_material": "Transformers are a neural network architecture that uses self-attention mechanisms to process sequential data. Unlike RNNs, transformers can process all tokens in parallel, making them more efficient. Key components include: Multi-head Self-Attention (allows the model to focus on different parts of the input), Positional Encoding (provides sequence order information), and Feed-Forward Networks (process attended information).",
            "quizzes": [
                {"question": "What is the key advantage of transformers over RNNs?", "answer": "Parallel processing of all tokens"},
                {"question": "What does self-attention do?", "answer": "Allows the model to focus on different parts of the input"}
            ],
            "description": "Complex multi-step: arxiv search + supplement explanation + final_response"
        },
        {
            "query": "summarize one most important concept I must learn with respect to the study material, then search for a youtube video tutorial explaining the main concept, finally book myself for 2 hrs on Friday this week to focus on studying",
            "chapter": "Deep Learning Fundamentals",
            "subtopic": "Neural Networks",
            "study_material": "Neural networks are computational models inspired by the human brain. They consist of interconnected nodes (neurons) organized in layers. Key concepts include: activation functions (ReLU, sigmoid), backpropagation for training, and gradient descent optimization.",
            "quizzes": [
                {"question": "What is backpropagation?", "answer": "Algorithm for training neural networks by computing gradients"},
                {"question": "What does an activation function do?", "answer": "Introduces non-linearity to the network"}
            ],
            "description": "Complex 3-task query: study_material + youtube_search + book_calendar + final_response"
        },
        {
            "query": "Tell me about Sweden and find a YouTube tutorial about it",
            "chapter": "World Geography",
            "subtopic": "Nordic Countries",
            "study_material": "The Nordic countries include Denmark, Finland, Iceland, Norway, and Sweden. These nations share cultural, historical, and linguistic ties.",
            "quizzes": [
                {"question": "Which countries are considered Nordic?", "answer": "Denmark, Finland, Iceland, Norway, and Sweden"}
            ],
            "description": "Two-task query: study_material about Sweden + youtube_search about Sweden"
        },
        {
            "query": "summarize what I should focus on for this chapter",
            "chapter": "Chinese Cuisine Fundamentals",
            "subtopic": "Kung Pao Chicken Preparation",
            "study_material": "Kung Pao Chicken is a classic Sichuan dish known for its bold flavors and spicy kick. The key components include: diced chicken marinated in soy sauce and cornstarch, dried red chilies for heat, Sichuan peppercorns for numbing sensation, peanuts for crunch, and a savory-sweet sauce made with soy sauce, rice vinegar, sugar, and cornstarch. The cooking technique involves high heat stir-frying to achieve the characteristic 'wok hei' or breath of wok flavor.",
            "quizzes": [
                {"question": "What gives Kung Pao Chicken its characteristic numbing sensation?", "answer": "Sichuan peppercorns"},
                {"question": "What is 'wok hei'?", "answer": "The breath of wok flavor from high heat stir-frying"}
            ],
            "description": "Study material query - summarization request"
        },
        {
            "query": "can you order me a pizza for delivery and also check the weather forecast for tomorrow?",
            "chapter": "Database Systems",
            "subtopic": "SQL Queries and Joins",
            "study_material": "SQL (Structured Query Language) is used to manage and manipulate relational databases. A JOIN clause combines rows from two or more tables based on a related column between them. Common types include INNER JOIN (returns matching records), LEFT JOIN (returns all records from left table and matching from right), RIGHT JOIN (opposite of left), and FULL JOIN (returns all records when there's a match in either table).",
            "quizzes": [
                {"question": "What does an INNER JOIN do?", "answer": "Returns only the matching records from both tables"},
                {"question": "What is the difference between LEFT JOIN and RIGHT JOIN?", "answer": "LEFT JOIN returns all from left table, RIGHT JOIN returns all from right table"}
            ],
            "description": "Query that cannot be fulfilled - requires tools not available (food delivery, weather)"
        }
    ]
    
    print("\n" + "="*80)
    print("QUERY DECOMPOSITION TESTING - Simple to Complex Queries")
    print("="*80)
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'─'*80}")
        print(f"Test Case {i}: {test['description']}")
        print(f"{'─'*80}")
        print(f"Query: \"{test['query']}\"")
        print(f"Chapter: {test['chapter']}")
        print(f"Subtopic: {test['subtopic']}")
        print(f"Study Material: {test['study_material'][:100]}...")
        
        result = query_decomposition_call(
            user_input=test['query'],
            chapter_name=test['chapter'],
            sub_topic=test['subtopic'],
            study_material=test['study_material'],
            stringified=json.dumps(test['quizzes'], ensure_ascii=False),
            memory_section="",
            history_section=""
        )
        
        print(f"\n📋 Decomposition Result:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        # Pretty print the steps
        if result and len(result) > 0:
            decomp = result[0]
            print(f"\n✨ Summary: {'Multi-step' if decomp.get('multi_steps') else 'Simple'} ({len(decomp.get('output_steps', []))} steps)")
            for step in decomp.get('output_steps', []):
                print(f"   Step {step.get('step_nr')}: {step.get('tool_name')} - {step.get('rationale')}")
        print()