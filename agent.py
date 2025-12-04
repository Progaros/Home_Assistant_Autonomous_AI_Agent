# /config/python_scripts/agent.py
# LLMs were used to generate and edit this script.
# NOTE: No imports allowed in HA python_script (RestrictedPython sandbox).

"""
===============================================================================
                    HOME ASSISTANT AUTONOMOUS AI AGENT
===============================================================================

OVERVIEW:
---------
This script implements an autonomous smart home agent that runs within
Home Assistant's python_script integration. It uses an LLM (e.g. Ollama) to
analyze context, make decisions, and take actions proactively.

ARCHITECTURE:
-------------
1. DATA COLLECTION
   - Gathers context: weather, calendar, tasks, birthdays, sensors, S-Bahn
   - Loads user memory (facts and corrections)
   - Builds time-aware routine hints

2. MAIN LOOP (max MAX_ITERATIONS cycles)
   - Constructs a rich prompt with all context
   - Calls LLM to get next tool decision
   - Parses response: TOOL / REASON / CONTENT format
   - Executes tool and records result
   - Repeats until FINISH or max iterations

3. TOOL SYSTEM (12 tools)
   Planning:    PLAN - Create multi-step action plan
   Reading:     READ_MEMORY, GET_ENTITY_STATE, GET_SBAHN, GET_WEATHER, SEARCH_WEB
   Actions:     CONTROL_DEVICE, SAVE_FACT, URGENT_ALERT, CALCULATE
   Completion:  DRAFT (iterative review), REVIEW, FINISH

4. SAFETY FEATURES
   - Entity ID validation with domain whitelist
   - Protected entity types (locks, alarms, cameras)
   - Device control validation (checks reason matches action)
   - Alert verification (double-checks with sensor data)
   - DRY_RUN_MODE for testing without real actions
   - Fact blocklist (prevents saving sensor data as facts)
   - Memory size limits

5. STATE TRACKING
   - agent_state dict tracks: history, plan, alerts, retries, drafts
   - History limited to MAX_HISTORY_LENGTH entries
   - Tool sequence logged for debugging

KEY CONSTRAINTS (HA python_script):
------------------------------------
- NO imports allowed (RestrictedPython sandbox)
- Must use HA built-ins: now(), hass, logger, data
- No dict() constructor - use {} or direct assignment
- No list comprehensions with complex expressions
- String concatenation instead of f-strings (for safety)

CONFIGURATION:
--------------
- DRY_RUN_MODE: Set False for production
- Adjust thresholds (CO2, calendar lookahead) as needed
- Customize PERSONAL_BACKGROUND_INFO for your use case
- Modify CALENDARS, TASK_LISTS for your entities

TRIGGERING:
-----------
Call via automation with:
  service: python_script.agent
  data:
    max_iterations: 10
    entity_memory: sensor.ai_memory_store
    llm_entity: ai_task.qwen3_instruct

===============================================================================
"""

# ═══════════════════════════════════════════════════════════════════════════════
#                         PERSONAL CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
# This section contains settings that are SPECIFIC TO YOUR SETUP.
# You MUST customize these values for the agent to work correctly.
#
# HOW TO CONFIGURE FOR A NEW USER:
# 1. Replace entity IDs with your own Home Assistant entities
# 2. Update calendar/task list names to match your setup
# 3. Customize personal background info with your own details
# 4. Set your preferred response language
# ═══════════════════════════════════════════════════════════════════════════════

# --- USER IDENTITY ---
# The name used in the system prompt. Change to your name.
USER_NAME = "User"

# --- LANGUAGE ---
# Language for agent responses. The agent will write messages in this language
# and verify compliance before sending.
# Examples: "German", "English", "French", "Spanish", "Italian", "Dutch"
RESPONSE_LANGUAGE = "German"

# --- HOME ASSISTANT ENTITIES ---
# These must match entity IDs in YOUR Home Assistant installation.
# Find them in HA: Developer Tools > States

# Memory storage entity (template sensor that stores learned facts)
# Create a template sensor with attributes: learned_facts, correction_log
ENTITY_MEMORY = data.get("entity_memory", "sensor.ai_memory_store")

# Event names for Home Assistant automations
# EVENT_MEMORY: Fired when agent wants to save a fact (trigger your memory automation)
# EVENT_NOTIFY: Fired when agent has a message for the user
EVENT_MEMORY = "set_ai_memory"
EVENT_NOTIFY = "set_personalized_text"  # Change to your name

# Notification service for mobile app
# Find yours: Developer Tools > Services > search "notify"
# Usually: "mobile_app_<your_phone_name>"
NOTIFY_SERVICE = data.get("notify_service", "mobile_app_phone")

# LLM entity from the ai_task integration
# Must match your configured AI Task entity
LLM_ENTITY = data.get("llm_entity", "ai_task.qwen3_instruct")

# --- WEATHER ---
# Your weather entity (usually created by weather integrations)
WEATHER_ENTITY = "weather.home"

# --- CALENDARS ---
# List ALL calendar entities you want the agent to check.
# Find them: Developer Tools > States > filter "calendar."
# Remove or add calendars as needed.
# e.g. ["calendar.personal", "calendar.work"]
CALENDARS = []

# Birthday calendar (usually from contacts integration)
# Set to [] if you don't have one
# e.g. ["calendar.birthdays"]
BIRTHDAY_CALENDARS = []

# --- TASK LISTS ---
# Your todo/task list entities from the todo integration.
# Find them: Developer Tools > States > filter "todo."
# e.g. ["todo.tasks", "todo.work"]
TASK_LISTS = []

# --- TRANSPORT / COMMUTE ---
# Public transport stations for departure tracking.
# Uses sensors from GTFS, public transport integrations, or similar.
#
# HOW TO CONFIGURE:
# Each station is a dict with:
#   - "id": Short identifier used in GET_SBAHN tool (e.g., "home", "work", "hbf")
#   - "name": Human-readable name shown in messages
#   - "entity": Home Assistant sensor entity ID
#   - "aliases": Alternative names the LLM can use (optional)
#
# The first station is the default when no direction is specified.
# Set to [] if you don't use public transport tracking.
#
# EXAMPLE FOR DIFFERENT CITY:
#   {"id": "home", "name": "Hauptbahnhof", "entity": "sensor.hbf_departures", "aliases": ["hbf", "main"]},
#   {"id": "work", "name": "Büro Station", "entity": "sensor.buero_departures", "aliases": ["office"]},
#
TRANSPORT_STATIONS = [
    # Example entries removed to keep configuration generic by default.
    # Please configure this list to match your Home Assistant sensors.
    # Recommended: set to [] when you don't use public transport tracking.
]

# Template/example (commented) - copy and adapt into TRANSPORT_STATIONS when needed:
# TRANSPORT_STATIONS = [
#     {
#         "id": "home",                     # short id used by GET_SBAHN tool
#         "name": "Hauptbahnhof",          # human-readable name shown in messages
#         "entity": "sensor.hbf_departures", # sensor entity providing departures
#         "aliases": ["hbf", "hauptbahnhof", "main"]  # optional alias keywords
#     },
#     {
#         "id": "work",
#         "name": "Office Station",
#         "entity": "sensor.office_departures",
#         "aliases": ["office", "work"]
#     }
# ]

# --- SENSORS ---
# CO2 sensor for air quality monitoring.
# Set to "" if you don't have one (disable CO2 alerts).
# e.g. "sensor.co2"
CO2_SENSOR = ""

# --- PERSONAL BACKGROUND ---
# Information about you that helps the agent personalize responses.
# This is included in every prompt to give context.
#
# TEMPLATE FOR NEW USERS: (structure from some git repo i sadly can't find anymore)
# Replace with your own information or leave sections empty.
# The agent uses this to understand your life context.
#
PERSONAL_BACKGROUND_INFO = """**BACKGROUND INFORMATION about {USER_NAME} (for context):**

  ## HISTORY
  ## PROBLEMS
  ## MISSION
  ## NARRATIVES
  ## GOALS
  ## CHALLENGES
  ## THINGS I'VE BEEN WRONG ABOUT
  ## IDEAS
  ## PREDICTIONS
  ## BEST MOVIES & Games
  ## WISDOM
  ## TRAUMATA"""


# ═══════════════════════════════════════════════════════════════════════════════
#                         AGENT BEHAVIOR SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════
# These settings control HOW the agent behaves.
# Adjust these to tune the agent's autonomy and response style.
# ═══════════════════════════════════════════════════════════════════════════════

# --- TESTING MODE ---
# When True, the agent simulates actions without actually controlling devices.
# Sends "DRY RUN" notifications instead of real device commands.
# Set to False for production use! The agent will control the real world.
# BE AWARE OF POTENTIAL RISKS - IT COULD TURN OFF LIGHTS, ADJUST THERMOSTATS, OR EVEN e.g. A FIREPLACE if MISCONFIGURED!
DRY_RUN_MODE = True

# --- TOOL TEST MODE ---
# When enabled, forces the agent to cycle through ALL tools for testing.
# The agent will ignore LLM decisions and execute each tool in sequence.
# Set to False for normal operation!
#
# Test sequence: PLAN -> READ_MEMORY -> GET_ENTITY_STATE -> GET_SBAHN -> GET_WEATHER ->
#                SEARCH_WEB -> CALCULATE -> CONTROL_DEVICE -> SAVE_FACT -> 
#                URGENT_ALERT -> DRAFT -> FINISH
TOOL_TEST_MODE = False

# Test data for each tool (customize as needed for your setup)
TOOL_TEST_DATA = {
    "PLAN": "1. Test all tools | 2. Check results | 3. Finish",
    "READ_MEMORY": "",
    "GET_ENTITY_STATE": "sensor.scd30_co2",  # Change to an entity you have
    "GET_SBAHN": "home",
    "GET_WEATHER": "",  # No content needed
    "SEARCH_WEB": "weather munich",
    "CALCULATE": "42 * 2 + 16",
    "CONTROL_DEVICE": "light.test|turn_on",  # Change to a safe test light
    "SAVE_FACT": "Test fact from tool test mode - can be deleted",
    "URGENT_ALERT": "TEST ALERT - ignore this",
    "DRAFT": "Dies ist eine Testnachricht vom Tool-Test-Modus.",
    "FINISH": "Tool-Test abgeschlossen! Alle Tools wurden getestet."
}

# --- PROACTIVE BEHAVIOR ---
# These settings control when the agent takes autonomous actions.

# CO2 threshold (ppm) to trigger ventilation alert
# Typical values: 800 (strict), 1000 (normal), 1200 (relaxed)
AUTO_ACT_CO2_THRESHOLD = 1050

# Minutes before a calendar event to check transport times
# The agent will look up S-Bahn times if an event is within this window
AUTO_ACT_CALENDAR_LOOKAHEAD_MIN = 90

# Master switch for proactive actions
# If False, agent only responds to explicit requests
ENABLE_PROACTIVE_ACTIONS = True

# --- DATA COLLECTION ---
# How far ahead to look for calendar events and birthdays

# Hours ahead to check for calendar events (e.g., 18 = rest of day + next morning)
CALENDAR_LOOKAHEAD_HOURS = 18

# Days ahead to check for birthdays
BIRTHDAY_DURATION_DAYS = 7


# ═══════════════════════════════════════════════════════════════════════════════
#                         TECHNICAL LIMITS & CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
# These settings control internal limits and thresholds.
# Only change if you understand the implications.
# ═══════════════════════════════════════════════════════════════════════════════

# --- MESSAGE LIMITS ---
# Maximum characters for the final message sent to user
MAX_MESSAGE_LENGTH = 500

# Maximum characters for review/draft validation (slightly higher to allow editing)
MAX_REVIEW_LENGTH = 550

# Maximum characters to include from web search results
MAX_WEB_RESULT_LENGTH = 2000

# --- ITERATION LIMITS ---
# Maximum tool calls per agent run (prevents infinite loops)
# Note: TOOL_TEST_MODE automatically uses 13 iterations to test all tools
MAX_ITERATIONS = data.get("max_iterations", 10)
if TOOL_TEST_MODE:
    MAX_ITERATIONS = 13  # 12 tools + 1 buffer

# Maximum consecutive parse errors before aborting
MAX_CONSECUTIVE_ERRORS = 5

# Maximum times to retry a failed tool before suggesting alternatives
MAX_TOOL_RETRIES = 2

# Maximum DRAFT iterations for message refinement
MAX_REVIEW_ITERATIONS = 3

# Number of personas to use for draft generation (3-5 recommended)
NUM_DRAFT_PERSONAS = 5

# --- MEMORY LIMITS ---
# Maximum length for a single saved fact
MAX_FACT_LENGTH = 200

# Home Assistant attribute size limits (bytes)
# HA has a hard limit of 16KB per entity's attributes
MAX_ATTR_SIZE = 16384
ATTR_SIZE_WARNING = 14000  # Warn when approaching limit

# Maximum history entries to keep in agent context
MAX_HISTORY_LENGTH = 20

# --- DISPLAY LIMITS ---
# Characters to show in log previews
LOG_CONTENT_PREVIEW = 600

# Characters to show for entity attributes in results
ATTRS_PREVIEW_LENGTH = 500

# Characters to show for reason field in history
REASON_PREVIEW_LENGTH = 100

# Characters to show for memory previews
MEMORY_FACTS_PREVIEW = 500
MEMORY_CORRECTIONS_PREVIEW = 400

# --- CALCULATION LIMITS ---
# Maximum expression length for CALCULATE tool (security measure)
MAX_EXPRESSION_LENGTH = 50

# --- LOGGING ---
# Prefix for all log messages (helps filter in HA logs)
LOG_PRE = ">>>AGNT<<<"


# ═══════════════════════════════════════════════════════════════════════════════
#                         SAFETY & VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════
# These settings control what the agent is allowed to do.
# Modify with caution - these are security boundaries.
# ═══════════════════════════════════════════════════════════════════════════════

# --- RETRY ALTERNATIVES ---
# When a tool fails, suggest these alternatives to the LLM
# Format: { "FAILED_TOOL": ["alternative1", "alternative2"] }
RETRY_ALTERNATIVES = {
    "SEARCH_WEB": ["GET_ENTITY_STATE", "FINISH"],
    "GET_ENTITY_STATE": ["FINISH"],
    "CONTROL_DEVICE": ["GET_ENTITY_STATE", "FINISH"],
    "CALCULATE": ["FINISH"],
}

# --- FACT BLOCKLIST ---
# Words that indicate transient sensor data (should NOT be saved as permanent facts)
# The agent will reject SAVE_FACT if the content contains these words
# TODO: For English users, add English equivalents: "temperature", "weather", "brightness", etc.
FACT_BLOCKLIST = [
    "co2", "ppm", "grad", "wetter", "temperatur", "luftfeuchtigkeit",
    "humidity", "pressure", "druck", "lux", "helligkeit", "bewegung",
    "motion", "battery", "batterie", "akku", "rssi", "signal"
]

# -------------------------------------------------------
# SYSTEM PROMPT
# -------------------------------------------------------
# This is the main instruction set for the LLM. It defines:
# - The agent's role and mission
# - Available tools and their usage
# - Decision logic and anti-patterns
# - Time awareness rules
# - Output format requirements
#
# The prompt uses placeholders that get filled in the main loop.
# Keep this in sync with the actual tool implementations below.
# -------------------------------------------------------

SYSTEM_PROMPT = """<SYSTEM>
You are an AUTONOMOUS Smart-Home-Agent for {USER_NAME}.
You act PROACTIVELY and make your own decisions based on context and situation.

## RESPONSE LANGUAGE
You MUST write ALL messages to the user in {LANGUAGE}.
This applies to DRAFT and FINISH content. Use natural, fluent {LANGUAGE}.
Do NOT mix languages or use English phrases unless they are common loanwords.

## YOUR MISSION
Analyze the situation, detect problems/opportunities, act autonomously, and inform the user only when necessary.

## AUTONOMOUS BEHAVIOR
1. ANALYZE the full context first (sensors, time, calendar, weather)
2. DETECT need for action (problems, optimizations, reminders)
3. ACT autonomously when sensible (control devices, gather info)
4. PLAN multi-step actions ahead
5. INFORM the user with a useful summary

## PROACTIVE ACTIONS (execute AUTOMATICALLY when sensible)
- CO2 > 1000ppm? -> URGENT_ALERT, suggest ventilation
- Appointment in < 1h? -> Check S-Bahn, calculate departure time
- Birthday today? -> Mention it prominently

## TOOL CHAINING (use multiple tools sequentially)
Example chains:
- Check appointment -> GET_SBAHN -> Calculate departure -> Inform user
- Bad weather -> Check calendar -> Suggest alternative activities

## TOOLS

### Planning Tools
PLAN: Create a multi-step action plan BEFORE acting.
  - WHEN: ONLY at the start for complex tasks
  - CONTENT: List of steps (e.g. "1. Check CO2 | 2. Check windows | 3. FINISH")
  - IMPORTANT: After PLAN execute each step with the APPROPRIATE tool!
  - NEVER create a new PLAN while one is running!

### Information Tools (for READING)
READ_MEMORY: Load stored user preferences and corrections.
  - CONTENT: (leave empty)

GET_ENTITY_STATE: Read current state of a device/sensor.
  - CONTENT: entity_id (e.g. "binary_sensor.fenster_wohnzimmer")
  - ONLY for READING - not for controlling!

GET_SBAHN: Get S-Bahn departure times.
  - CONTENT: "home" or "hbf" (direction)
  - Returns next 3 departures

GET_WEATHER: Get full weather forecast (48h hourly + weekly).
  - CONTENT: (leave empty)
  - Use when user asks about weather, planning outdoor activities, or needs detailed forecast
  - Default context only shows current + next 6h - use this for more details

SEARCH_WEB: Search for external information.
  - CONTENT: Search query

CALCULATE: Mathematical calculations.
  - CONTENT: Expression (e.g. "45 + 15")

### Action Tools (for CONTROLLING)
CONTROL_DEVICE: Control devices (NOT for reading!).
  - CONTENT: entity_id|action|[params]
  - Actions: turn_on, turn_off, toggle, set_value
  - Example: "light.flur|turn_on|brightness=50"
  - ONLY for: Light on/off, climate, blinds
  - NOT for: Reading sensors, checking window status

SAVE_FACT: Save important user info permanently.
  - CONTENT: Fact (only personal preferences, NO sensor data!)

URGENT_ALERT: ONLY for real emergencies (CO2>1000, intrusion, fire).
  - CONTENT: Alert message

### Completion Tools
DRAFT: Generate persona-based drafts and merge into final message.
  - CONTENT: ONLY bullet points of RAW FACTS to mention (from tool results!)
  - Format: "- Fact 1\n- Fact 2\n- Fact 3" (NO prose, NO sentences!)
  - DO NOT write a message - just list facts from GET_ENTITY_STATE, GET_WEATHER, etc.
  - WRONG: "{USER_NAME}, heute Abend war es klar..." (this is a message!)
  - RIGHT: "- Weather: clear, 5°C\n- CO2: 912 ppm\n- Tomorrow: Termin mit Ernst"
  - System generates different persona messages from your bullet points
  - Returns merged best-of-all draft for your review

FINISH: Send final message to user.
  - CONTENT: Message (max 500 chars, plain text + 1-3 emojis)
  - NO Markdown, NO HTML!

## DECISION LOGIC

```
FIRST STEP (ALWAYS!):
    -> READ_MEMORY (unless already done this session)
    -> User preferences are stored here!

THEN:
IF critical_sensor_alarm:
    -> URGENT_ALERT immediately
ELIF action_needed_detected:
    -> Chain tools until problem solved
    -> DRAFT -> FINISH with summary
ELSE:
    -> Analyze context -> DRAFT helpful message -> FINISH
```

## USER CORRECTIONS (HIGHEST PRIORITY!)
Corrections in Memory are COMMANDS for FUTURE behavior!
Example: "earliest 5am good morning" = No morning greeting before 5am!
Do NOT mention or explain corrections in message - just follow them!

## TIME AWARENESS
Adapt tone and content STRICTLY to current time of day:
- Morning (5-11): Daily overview, weather, important appointments, "Good morning"
- Noon (11-14): Short and brief. ONLY current info
- Afternoon (14-18): Reminders, planning
- Evening (18-23): Relaxed tone, daily review. Check MEMORY for user's actual sleep time!
- Night (23-5): Minimal. Only active for real problems

TIME ERRORS TO AVOID:
- NEVER assume user sleeps at 21:00 or 22:00 - CHECK MEMORY for actual sleep time!
- Do NOT say "go to sleep" or "time for bed" without knowing user's schedule!
- At noon NO morning/evening/night references
- NO countdowns or time calculations to other times of day
- Do NOT explain user corrections - just follow them silently!
- Message must fit the CURRENT time!

## FORMAT (follow EXACTLY - ONE tool per response!)
TOOL: [TOOL_NAME]
REASON: [Why this action now?]
CONTENT: [Content for this tool]

IMPORTANT:
- ONLY ONE tool per response!
- CONTENT contains ONLY the content for the chosen tool
- Do NOT mix multiple tools in CONTENT!

## ANTI-PATTERNS (AVOID!)
- Always same tool sequence
- Only READ_MEMORY -> FINISH without analysis
- Asking user instead of acting yourself
- Repeating obvious info
- Generic messages without value
</SYSTEM>"""

# -------------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------------
# These functions provide core utilities used throughout the agent.
# They are designed to work within HA's RestrictedPython sandbox.
# -------------------------------------------------------

def log_msg(msg, iter_idx=0):
    """Log an INFO message with agent prefix and iteration number."""
    logger.info(LOG_PRE + " [It:" + str(iter_idx) + "] " + str(msg))

def log_debug(msg, iter_idx=0):
    """Log a DEBUG message with agent prefix and iteration number."""
    logger.debug(LOG_PRE + " [It:" + str(iter_idx) + "] " + str(msg))

def log_warn(msg, iter_idx=0):
    """Log a WARNING message with agent prefix and iteration number."""
    logger.warning(LOG_PRE + " [It:" + str(iter_idx) + "] " + str(msg))

def log_error(msg, iter_idx=0):
    """Log an ERROR message with agent prefix and iteration number."""
    logger.error(LOG_PRE + " [It:" + str(iter_idx) + "] " + str(msg))

def get_attr(entity_id, attr, default=None):
    """Get a specific attribute from an entity's state object.
    
    Args:
        entity_id: The entity to query (e.g., 'sensor.temperature')
        attr: The attribute name to retrieve
        default: Value to return if entity or attribute not found
    
    Returns:
        The attribute value or default
    """
    state_obj = hass.states.get(entity_id)
    if state_obj and attr in state_obj.attributes:
        return state_obj.attributes[attr]
    return default

def get_state(entity_id):
    """Get the state of an entity."""
    state_obj = hass.states.get(entity_id)
    if state_obj:
        attrs = {}
        if state_obj.attributes:
            for key in state_obj.attributes:
                attrs[key] = state_obj.attributes[key]
        return {
            "state": state_obj.state,
            "attributes": attrs,
            "last_changed": str(state_obj.last_changed) if state_obj.last_changed else "unknown"
        }
    return None

def format_timestamp(ts, fmt='%H:%M'):
    """Format a timestamp string without imports (HA python_script compatible)."""
    try:
        ts_str = str(ts)
        # Handle ISO format: extract time/date parts manually
        if 'T' in ts_str:
            date_part, time_part = ts_str.split('T')
            time_clean = time_part.split('+')[0].split('-')[0].split('Z')[0]
            if fmt == '%H:%M':
                return time_clean[:5]
            elif fmt == '%H:%M %d.%m.%Y':
                date_parts = date_part.split('-')
                return time_clean[:5] + ' ' + date_parts[2] + '.' + date_parts[1] + '.' + date_parts[0]
            elif fmt == '%d.%m.':
                date_parts = date_part.split('-')
                return date_parts[2] + '.' + date_parts[1] + '.'
            elif fmt == '%A':
                # Return date string, can't get weekday name without imports
                return date_part
        # Handle date-only format (YYYY-MM-DD)
        elif len(ts_str) == 10 and ts_str[4] == '-':
            date_parts = ts_str.split('-')
            if fmt == '%d.%m.':
                return date_parts[2] + '.' + date_parts[1] + '.'
            return ts_str
    except:
        pass
    return str(ts)

def check_attr_size(entity_id, warn_user=True):
    """Check if entity attributes are approaching size limit. Returns (size, is_warning, is_critical)."""
    state_obj = hass.states.get(entity_id)
    if not state_obj or not state_obj.attributes:
        return 0, False, False
    
    # Estimate size (convert to string representation)
    # Note: Can't use dict() in HA python_script, use str() directly
    attr_str = str(state_obj.attributes)
    size = len(attr_str)
    
    is_warning = size >= ATTR_SIZE_WARNING
    is_critical = size >= MAX_ATTR_SIZE - 500  # 500 byte buffer
    
    if warn_user and is_warning:
        log_warn(entity_id + " attributes size: " + str(size) + "/" + str(MAX_ATTR_SIZE) + " bytes (" + str(size*100//MAX_ATTR_SIZE) + "% full)", 0)
    
    if is_critical:
        log_error(entity_id + " attributes near limit! Consider clearing old data.", 0)
    
    return size, is_warning, is_critical

def notify_dry_run(action_desc):
    """Send a notification instead of performing action (for DRY_RUN_MODE)."""
    if DRY_RUN_MODE:
        try:
            hass.services.call("notify", NOTIFY_SERVICE, {
                "title": "🧪 DRY RUN",
                "message": "Would execute: " + str(action_desc)
            })
        except Exception as e:
            log_error("Dry run notification failed: " + str(e), 0)
        return True
    return False

def sanitize_input(text, extra_forbidden=None):
    """Sanitize user input to prevent injection attacks."""
    forbidden_chars = [";", "&", "|", "`", "$", "(", ")", "<", ">", "\\", "!", "\n", "\r", '"', "'", "{", "}"]
    if extra_forbidden:
        forbidden_chars.extend(extra_forbidden)
    safe_text = str(text)
    for char in forbidden_chars:
        safe_text = safe_text.replace(char, "")
    return safe_text.strip()

def validate_entity_id(entity_id):
    """Validate that an entity_id looks legitimate."""
    entity_id = str(entity_id).strip().lower()
    if "." not in entity_id:
        return None
    parts = entity_id.split(".")
    if len(parts) != 2:
        return None
    domain, name = parts
    # Whitelist of allowed domains
    allowed_domains = [
        "light", "switch", "sensor", "binary_sensor", "climate", "cover",
        "fan", "media_player", "vacuum", "input_boolean", "input_number",
        "input_select", "input_text", "scene", "script", "person",
        "device_tracker", "weather", "sun", "zone", "calendar", "todo"
    ]
    if domain not in allowed_domains:
        return None
    # Basic name validation (alphanumeric and underscores only)
    if not all(c.isalnum() or c == "_" for c in name):
        return None
    return entity_id

def validate_device_control(entity_id, action, reason, plan_step=""):
    """
    Validate if a device control action makes sense given the context.
    
    This prevents the LLM from taking nonsensical actions like turning on
    lights "because of high CO2" - the reason must match the device type.
    
    Args:
        entity_id: The device to control
        action: The action (turn_on, turn_off, etc.)
        reason: The LLM's stated reason for the action
        plan_step: Current plan step (provides additional context)
    
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
    
    Domain-specific keywords:
        - light: dunkel, hell, licht, sehen, abend, nacht, etc.
        - climate: kalt, warm, temperatur, heiz, kühl, etc.
        - cover: sonne, dunkel, rollo, jalousie, etc.
    """
    if not entity_id:
        return False, "No entity_id provided"
    
    domain = entity_id.split(".")[0] if "." in entity_id else ""
    
    # Check protected entities
    protected = ["lock.", "alarm_control_panel.", "camera."]
    for p in protected:
        if entity_id.startswith(p):
            return False, "Protected entity type: " + p
    
    # Validate action makes sense for the reason given
    reason_lower = reason.lower() if reason else ""
    plan_lower = plan_step.lower() if plan_step else ""
    combined_context = reason_lower + " " + plan_lower
    
    # Light-specific validation
    if domain == "light":
        light_keywords = ["dunkel", "hell", "licht", "sehen", "abend", "nacht", 
                          "morgen", "aufstehen", "schlafen", "beleuch", "lamp"]
        has_light_reason = any(kw in combined_context for kw in light_keywords)
        
        # Reject if no light-related reason
        if not has_light_reason:
            return False, "No valid reason for light control. Reason: '" + reason + "' doesn't mention lighting needs."
    
    # Climate-specific validation  
    if domain == "climate":
        climate_keywords = ["kalt", "warm", "temperatur", "heiz", "kühl", "frieren"]
        if not any(kw in combined_context for kw in climate_keywords):
            return False, "No valid reason for climate control."
    
    # Cover/blinds validation
    if domain == "cover":
        cover_keywords = ["sonne", "dunkel", "rollo", "jalousie", "fenster", "blend"]
        if not any(kw in combined_context for kw in cover_keywords):
            return False, "No valid reason for cover control."
    
    return True, None

def is_fact_blocked(content):
    """Check if a fact contains blocked transient data patterns."""
    lower_c = content.lower()
    for pattern in FACT_BLOCKLIST:
        if pattern in lower_c:
            return True
    # Also block if it looks like a number/measurement
    words = lower_c.split()
    for word in words:
        clean_word = word.replace(",", ".").replace("°", "").replace("%", "")
        try:
            float(clean_word)
            if len(words) < 5:  # Short messages with numbers are likely sensor data
                return True
        except ValueError:
            pass
    return False

def validate_message(content):
    """Validate a message for REVIEW/FINISH.
    
    Checks for common issues that would make the message display
    incorrectly in Home Assistant notifications:
    - Empty content
    - Excessive length
    - HTML tags (not rendered in notifications)
    - Markdown formatting (not rendered in notifications)
    - Escape sequences
    
    Args:
        content: The message to validate
    
    Returns:
        List of issue strings (empty if valid)
    """
    issues = []
    
    if not content or len(content.strip()) == 0:
        issues.append("Message is empty")
        return issues
    
    if len(content) > MAX_REVIEW_LENGTH:
        issues.append("Too long (" + str(len(content)) + " chars, max " + str(MAX_MESSAGE_LENGTH) + ")")
    
    # Check for HTML
    if "<" in content and ">" in content:
        lower_c = content.lower()
        html_tags = ["<br", "<p", "<div", "<span", "<b>", "<i>", "<strong>", "<em>", 
                     "<ul>", "<li>", "<h1>", "<h2>", "<h3>", "<html>", "<body>", "</a>",
                     "<table", "<tr", "<td", "<script", "<style", "<img", "<a "]
        if any(x in lower_c for x in html_tags):
            issues.append("Contains HTML tags (use plain text only)")
    
    # Check for Markdown
    markdown_patterns = ["**", "##", "```", "* ", "- [ ]", "[](", "!["]
    for pattern in markdown_patterns:
        if pattern in content:
            issues.append("Contains Markdown formatting '" + pattern + "' (use plain text only)")
            break
    
    # Check for weird characters
    if "\\n" in content or "\\t" in content:
        issues.append("Contains escape sequences (use actual line breaks if needed)")
    
    return issues

def verify_language(content, expected_language):
    """
    Use AI to verify that the message is in the expected language.
    
    Args:
        content: The message text to verify
        expected_language: The expected language (e.g., "German")
    
    Returns:
        Tuple of (is_correct: bool, feedback: str)
    """
    if not content or len(content) < 10:
        return True, ""  # Too short to verify
    
    try:
        verify_prompt = """<SYSTEM>
LANGUAGE VERIFICATION MODE.
Expected language: """ + expected_language + """
Message to verify: """ + content + """

Is this message written in """ + expected_language + """?
Ignore common loanwords, brand names, or technical terms.
Focus on whether the main text is in the correct language.

Answer format:
LANGUAGE_OK: YES or NO
ISSUE: (only if NO - briefly explain what language it appears to be)
</SYSTEM>"""
        
        verify_call = hass.services.call(
            "ai_task", "generate_data",
            {"entity_id": LLM_ENTITY, "task_name": "Verify Language", "instructions": verify_prompt},
            blocking=True, return_response=True
        )
        verify_res = str(verify_call.get("data", "")).strip().upper()
        
        if "LANGUAGE_OK: YES" in verify_res or "YES" in verify_res.split("\n")[0]:
            return True, ""
        else:
            # Extract issue if present
            issue = "Message appears to be in wrong language. Please rewrite in " + expected_language + "."
            if "ISSUE:" in verify_res:
                issue_line = verify_res.split("ISSUE:")[1].strip().split("\n")[0]
                if issue_line:
                    issue = "Language issue: " + issue_line + ". Please rewrite in " + expected_language + "."
            return False, issue
    except Exception as e:
        log_warn("Language verification failed: " + str(e), 0)
        return True, ""  # Don't block on verification errors


# -------------------------------------------------------
# PERSONA-BASED DRAFT GENERATION
# -------------------------------------------------------
# These personas provide different perspectives for message crafting.
# Each persona emphasizes different communication styles.
# -------------------------------------------------------

DRAFT_PERSONAS = [
    {
        "name": "Concise",
        "style": "Brief, efficient, action-focused. Get to the point quickly. No fluff. Maximum information density. Use short sentences.",
        "emoji_style": "minimal (0-1 emoji)"
    },
    {
        "name": "Warm",
        "style": "Friendly, empathetic, personal. Show you care about the user. Use their name. Add warmth and human connection. Be supportive.",
        "emoji_style": "moderate (1-2 friendly emojis)"
    },
    {
        "name": "Informative",
        "style": "Detailed, comprehensive, educational. Provide context and reasoning. Explain the 'why'. Be thorough but organized.",
        "emoji_style": "functional (1 relevant emoji)"
    },
    {
        "name": "Playful",
        "style": "Light-hearted, uses gentle humor. Make information enjoyable. Add personality and wit. Keep it fun but not silly.",
        "emoji_style": "expressive (2-3 fun emojis)"
    },
    {
        "name": "Professional",
        "style": "Formal, structured, reliable. Like a trusted assistant. Clear and organized. Respectful and polished.",
        "emoji_style": "conservative (0-1 subtle emoji)"
    }
]


def generate_persona_drafts(topic, context_summary, user_name, language):
    """Generate multiple draft messages from different persona perspectives.
    
    Calls the LLM SEPARATELY for each persona to prevent shared hallucinations.
    Each persona generates in isolation, then drafts are fact-checked and merged.
    
    Args:
        topic: The key points/topic to communicate
        context_summary: Brief context about current situation
        user_name: The user's name for personalization
        language: Target language for the message
    
    Returns:
        Tuple of (merged_draft: str, persona_drafts: list, merge_notes: str, fact_check_result: str)
    """
    # Select personas (use NUM_DRAFT_PERSONAS, max 5)
    num_personas = min(NUM_DRAFT_PERSONAS, len(DRAFT_PERSONAS))
    selected_personas = DRAFT_PERSONAS[:num_personas]
    
    persona_drafts = []
    
    try:
        # Generate each persona draft in a SEPARATE LLM call
        # This prevents hallucinations from spreading across all personas
        for persona in selected_personas:
            single_persona_prompt = """<SYSTEM>
SINGLE PERSONA DRAFT GENERATION
Language: """ + language + """
User Name: """ + user_name + """

=== RAW FACTS TO MENTION (source of truth) ===
""" + topic + """

=== VERIFIED DATA (additional context) ===
""" + context_summary + """

YOUR PERSONA: """ + persona["name"].upper() + """
Style: """ + persona["style"] + """
Emoji usage: """ + persona["emoji_style"] + """

CRITICAL RULES:
1. ONLY mention facts that appear in RAW FACTS or VERIFIED DATA above
2. Do NOT add information that is not explicitly listed
3. Do NOT assume sleeping times, appointments, or events unless listed
4. Do NOT say "you usually sleep at..." unless it's in the data
5. If you're unsure about something, OMIT it rather than guess
6. Write in """ + language + """
7. Maximum 400 characters
8. Plain text only (no markdown, no HTML)

FORMAT YOUR RESPONSE EXACTLY:
---DRAFT---
[Your draft message here]
---END---
</SYSTEM>"""

            try:
                draft_response = hass.services.call(
                    "ai_task", "generate_data",
                    {"entity_id": LLM_ENTITY, "task_name": "Draft: " + persona["name"], "instructions": single_persona_prompt},
                    blocking=True, return_response=True
                )
                draft_raw = str(draft_response.get("data", ""))
                
                # Parse the single draft
                draft_text = ""
                if "---DRAFT---" in draft_raw:
                    start_idx = draft_raw.index("---DRAFT---") + len("---DRAFT---")
                    end_idx = draft_raw.index("---END---") if "---END---" in draft_raw else len(draft_raw)
                    draft_text = draft_raw[start_idx:end_idx].strip()
                else:
                    # Fallback: use raw output
                    draft_text = draft_raw.strip()[:400]
                
                persona_drafts.append({
                    "persona": persona["name"],
                    "draft": draft_text
                })
                log_msg("PERSONA [" + persona["name"] + "]: " + draft_text[:LOG_CONTENT_PREVIEW], 0)
                
            except Exception as persona_err:
                log_warn("Failed to generate " + persona["name"] + " draft: " + str(persona_err), 0)
                # Continue with other personas
        
        if not persona_drafts:
            # Fallback: no personas generated, return topic as draft
            log_warn("No persona drafts generated, using topic as fallback", 0)
            return topic[:500], [], "No drafts generated", ""
        
        # === FACT-CHECK STEP ===
        # Verify dates, times, numbers, and factual claims in drafts
        drafts_for_check = ""
        for pd in persona_drafts:
            drafts_for_check = drafts_for_check + "\n[" + pd["persona"] + "]: " + pd["draft"] + "\n"
        
        fact_check_prompt = """<SYSTEM>
FACT-CHECKER - Verify accuracy of dates, times, and facts in these drafts.

KNOWN CONTEXT (source of truth):
""" + context_summary + """

DRAFTS TO CHECK:
""" + drafts_for_check + """

CHECK FOR:
1. DATES: Are any dates mentioned correct based on context?
2. TIMES: Are times (appointments, departures, etc.) accurate?
3. NUMBERS: Are temperatures, CO2 levels, percentages correct?
4. EVENTS: Are calendar events, birthdays described accurately?
5. WEATHER: Does weather description match the data?

RESPONSE FORMAT:
---FACT_STATUS---
OK or ISSUES_FOUND
---CORRECTIONS---
[If issues: List each error and the correct value from context]
[If OK: "All facts verified correct"]
---END_FACTS---
</SYSTEM>"""

        fact_check_result = ""
        corrections_for_merge = ""
        try:
            fact_response = hass.services.call(
                "ai_task", "generate_data",
                {"entity_id": LLM_ENTITY, "task_name": "Fact Check", "instructions": fact_check_prompt},
                blocking=True, return_response=True
            )
            fact_raw = str(fact_response.get("data", ""))
            
            # Parse fact-check result
            if "---CORRECTIONS---" in fact_raw:
                corr_start = fact_raw.index("---CORRECTIONS---") + len("---CORRECTIONS---")
                corr_end = fact_raw.index("---END_FACTS---") if "---END_FACTS---" in fact_raw else len(fact_raw)
                corrections_for_merge = fact_raw[corr_start:corr_end].strip()
                
                if "ISSUES_FOUND" in fact_raw:
                    fact_check_result = "CORRECTIONS NEEDED: " + corrections_for_merge[:LOG_CONTENT_PREVIEW]
                    log_warn("FACT-CHECK: Issues found - " + corrections_for_merge[:100], 0)
                else:
                    fact_check_result = "Facts verified OK"
                    log_msg("FACT-CHECK: All facts verified OK", 0)
        except Exception as fc_err:
            log_warn("Fact-check failed: " + str(fc_err), 0)
            fact_check_result = "Fact-check skipped (error)"
            corrections_for_merge = ""
        
        # Now merge the drafts into one optimal message
        drafts_for_merge = ""
        for pd in persona_drafts:
            drafts_for_merge = drafts_for_merge + "\n[" + pd["persona"] + "]: " + pd["draft"] + "\n"
        
        # Include corrections in merge prompt if any were found
        corrections_instruction = ""
        if corrections_for_merge and "ISSUES_FOUND" in fact_raw:
            corrections_instruction = """

IMPORTANT - FACT CORRECTIONS REQUIRED:
""" + corrections_for_merge + """
You MUST apply these corrections in the merged message!"""
        
        merge_prompt = """<SYSTEM>
DRAFT MERGER - Create the optimal message by combining the best elements.
Language: """ + language + """
User Name: """ + user_name + """
Max Length: 500 characters

INPUT DRAFTS:""" + drafts_for_merge + corrections_instruction + """

YOUR TASK:
1. Identify the BEST elements from each draft:
   - Best opening/greeting
   - Most useful information
   - Best tone/warmth balance
   - Best emoji usage (1-3 total)
2. Combine into ONE optimal message
3. Ensure it's natural, not a Frankenstein patchwork
4. Keep it under 500 chars, plain text only

FORMAT:
---MERGED---
[Your merged optimal message here]
---NOTES---
[Brief notes on what you took from each persona]
</SYSTEM>"""

        merge_response = hass.services.call(
            "ai_task", "generate_data",
            {"entity_id": LLM_ENTITY, "task_name": "Merge Drafts", "instructions": merge_prompt},
            blocking=True, return_response=True
        )
        merge_raw = str(merge_response.get("data", ""))
        
        # Parse merged result
        merged_draft = ""
        merge_notes = ""
        
        if "---MERGED---" in merge_raw:
            start_idx = merge_raw.index("---MERGED---") + len("---MERGED---")
            end_idx = merge_raw.index("---NOTES---") if "---NOTES---" in merge_raw else len(merge_raw)
            merged_draft = merge_raw[start_idx:end_idx].strip()
        
        if "---NOTES---" in merge_raw:
            notes_idx = merge_raw.index("---NOTES---") + len("---NOTES---")
            merge_notes = merge_raw[notes_idx:].strip()[:200]
        
        if not merged_draft:
            # Fallback to first draft
            merged_draft = persona_drafts[0]["draft"] if persona_drafts else topic
            log_warn("MERGE: Fallback to first draft (parsing failed)", 0)
        else:
            log_msg("MERGED DRAFT: " + merged_draft[:LOG_CONTENT_PREVIEW], 0)
            if merge_notes:
                log_msg("MERGE NOTES: " + merge_notes[:150], 0)
        
        return merged_draft, persona_drafts, merge_notes, fact_check_result
        
    except Exception as e:
        log_error("Persona draft generation failed: " + str(e), 0)
        return topic, [], "Error: " + str(e), ""


def safe_calculate(expression):
    """Safely evaluate a mathematical expression without using eval."""
    expr = str(expression).replace(" ", "")
    
    # Handle modulo separately before main parsing
    if "%" in expr and "(" not in expr:
        parts = expr.split("%")
        if len(parts) == 2:
            try:
                left = float(parts[0])
                right = float(parts[1])
                return left % right, None
            except:
                pass
    
    # Only allow safe characters
    allowed = "0123456789+-*/.()%"
    for c in expr:
        if c not in allowed:
            return None, "Invalid characters in expression"
    
    if ".." in expr or "//" in expr or "**" in expr:
        return None, "Invalid operator sequence"
    
    if len(expr) > MAX_EXPRESSION_LENGTH:
        return None, "Expression too long"
    
    try:
        result = parse_expr(expr)
        return result, None
    except Exception as e:
        return None, "Calculation error: " + str(e)

def parse_expr(expr):
    """Simple expression parser for basic math with correct operator precedence.
    
    This implements a two-pass algorithm:
    1. Handle parentheses recursively (innermost first)
    2. Tokenize into numbers and operators
    3. First pass: process * and / (left to right)
    4. Second pass: process + and - (left to right)
    
    This ensures correct precedence (e.g., "10-5-2" = 3, not 7).
    
    Args:
        expr: String expression like "10+5*2" or "(10+5)*2"
    
    Returns:
        Float result of the calculation
    
    Raises:
        ValueError: For mismatched parentheses or division by zero
    """
    # Handle parentheses first (innermost first)
    while "(" in expr:
        start = expr.rfind("(")
        end = expr.find(")", start)
        if end == -1:
            raise ValueError("Mismatched parentheses")
        inner = expr[start+1:end]
        inner_result = parse_expr(inner)
        expr = expr[:start] + str(inner_result) + expr[end+1:]
    
    # Tokenize the expression
    tokens = []
    current_num = ""
    for i, c in enumerate(expr):
        if c in "+-*/" and current_num:
            tokens.append(float(current_num))
            tokens.append(c)
            current_num = ""
        elif c in "+-" and not current_num:
            # Handle negative numbers at start or after operator
            current_num = c
        else:
            current_num += c
    if current_num:
        tokens.append(float(current_num))
    
    if not tokens:
        return 0.0
    if len(tokens) == 1:
        return tokens[0]
    
    # First pass: handle * and / (left to right)
    i = 1
    while i < len(tokens):
        if tokens[i] == '*':
            result = tokens[i-1] * tokens[i+1]
            tokens = tokens[:i-1] + [result] + tokens[i+2:]
        elif tokens[i] == '/':
            if tokens[i+1] == 0:
                raise ValueError("Division by zero")
            result = tokens[i-1] / tokens[i+1]
            tokens = tokens[:i-1] + [result] + tokens[i+2:]
        else:
            i += 2
    
    # Second pass: handle + and - (left to right)
    result = tokens[0]
    i = 1
    while i < len(tokens):
        if tokens[i] == '+':
            result = result + tokens[i+1]
        elif tokens[i] == '-':
            result = result - tokens[i+1]
        i += 2
    
    return result

def parse_llm_text(text):
    """Parse LLM output to extract tool, reason, and content."""
    tool = "ERROR"
    reason = ""
    content = ""
    text = str(text).strip()
    
    if not text:
        return {"tool": "ERROR", "reason": "Empty LLM response", "content": ""}
    
    lines = text.split('\n')
    tool_found = False
    mode = None 
    
    for line in lines:
        clean_line = line.strip()
        upper_line = clean_line.upper()
        
        # Remove markdown bold/italic and list markers
        upper_line = upper_line.replace("*", "").lstrip("- ")

        if upper_line.startswith("TOOL:"):
            if tool_found: break
            raw_tool = clean_line.split(":", 1)[1].strip()
            tool = raw_tool.split(' ')[0].upper().replace("*", "")
            tool_found = True
            mode = None
        elif upper_line.startswith("REASON:"):
            if not tool_found: continue
            reason = clean_line.split(":", 1)[1].strip()
            mode = None
        elif upper_line.startswith("CONTENT:"):
            if not tool_found: continue
            content = clean_line.split(":", 1)[1].strip()
            mode = "content"
        elif mode == "content":
            if len(content) > 0: content += "\n" + line
            else: content = line
    
    # Cleanup content (remove quotes if wrapped)
    content = content.strip()
    if len(content) > 1 and ((content.startswith('"') and content.endswith('"')) or (content.startswith("'") and content.endswith("'"))):
         content = content[1:-1]
            
    return {"tool": tool, "reason": reason, "content": content}

# -------------------------------------------------------
# PLAN MANAGEMENT HELPERS
# -------------------------------------------------------
# These functions manage the multi-step planning system.
# Plans allow the agent to break complex tasks into steps and track progress.
# -------------------------------------------------------

def advance_plan(state):
    """Advance to the next plan step after completing current one.
    
    Args:
        state: The agent_state dictionary
    
    Returns:
        A message suffix to append to tool results, indicating next step
    """
    if not state["current_plan"] or state["plan_index"] >= len(state["current_plan"]):
        return ""
    
    state["plan_index"] = state["plan_index"] + 1
    
    if state["plan_index"] < len(state["current_plan"]):
        return "\n\n> Next plan step: " + state['current_plan'][state['plan_index']]
    else:
        return "\n\nPlan completed! Now FINISH."

def set_retry_state(state, tool_name):
    """Set retry state after a tool failure."""
    state["last_failed_tool"] = tool_name
    state["suggested_alternatives"] = RETRY_ALTERNATIVES.get(tool_name, [])
    retry_count = state["tool_retry_count"].get(tool_name, 0)
    if retry_count < MAX_TOOL_RETRIES:
        state["tool_retry_count"][tool_name] = retry_count + 1
        return " Retry " + str(retry_count + 1) + "/" + str(MAX_TOOL_RETRIES) + " possible, or alternatives: " + ", ".join(state["suggested_alternatives"])
    return " Max retries reached. Alternatives: " + ", ".join(state["suggested_alternatives"])

def clear_retry_state(state):
    """Clear retry state after success."""
    state["last_failed_tool"] = None
    state["suggested_alternatives"] = []

def parse_plan_content(content):
    """Parse plan content string into list of steps."""
    # Normalize all arrow separators
    plan_content = content.replace("→", "|").replace("->", "|").replace("=>", "|")
    raw_steps = plan_content.replace("|", "\n").split("\n")
    new_plan = []
    for step in raw_steps:
        step = step.strip()
        if not step:
            continue
        # Skip meta-instructions that aren't actual steps
        if step.startswith("👉") or step.startswith("---") or "starte jetzt" in step.lower():
            continue
        # Remove numbering like "1.", "1)", "1:", "Step 1:"
        if len(step) > 2:
            # Handle "1. " or "1) " or "1: "
            if step[0].isdigit() and len(step) > 1 and step[1] in ".):":
                step = step[2:].strip()
            # Handle "12. " (two digit numbers)
            elif len(step) > 3 and step[0].isdigit() and step[1].isdigit() and step[2] in ".):":
                step = step[3:].strip()
            # Handle "Step 1:" or "Schritt 1:"
            elif step.lower().startswith("step ") or step.lower().startswith("schritt "):
                colon_pos = step.find(":")
                if colon_pos > 0 and colon_pos < 15:
                    step = step[colon_pos + 1:].strip()
        # Skip empty or very short steps
        if step and len(step) > 2:
            new_plan.append(step)
    return new_plan

# -------------------------------------------------------
# DATA COLLECTION FUNCTIONS
# -------------------------------------------------------
# These functions gather context data from Home Assistant entities.
# Each returns a formatted string for inclusion in the LLM prompt.
# Errors are caught and return "... not available" to allow graceful degradation.
# -------------------------------------------------------

def collect_weather():
    """Fetch BRIEF weather summary for default prompt context.
    
    Returns only current conditions + next 6 hours to reduce prompt size.
    Use GET_WEATHER tool for full hourly (48h) and weekly forecast.
    
    Returns:
        Brief weather summary string (current + next 6 hours)
    """
    try:
        # Get current weather state
        weather_state = hass.states.get(WEATHER_ENTITY)
        current_condition = weather_state.state if weather_state else "unknown"
        current_temp = weather_state.attributes.get("temperature", "?") if weather_state else "?"
        
        weather_text = "Weather now: " + str(current_condition) + " (" + str(current_temp) + "C)"
        
        # Get only next 6 hours
        hourly_response = hass.services.call(
            "weather", "get_forecasts",
            {"entity_id": WEATHER_ENTITY, "type": "hourly"},
            blocking=True, return_response=True
        )
        
        if hourly_response and WEATHER_ENTITY in hourly_response:
            forecasts = hourly_response[WEATHER_ENTITY].get("forecast", [])[:6]
            if forecasts:
                weather_text = weather_text + "\nNext 6h:"
                for f in forecasts:
                    time_str = format_timestamp(f.get("datetime", ""), '%H:%M')
                    condition = f.get("condition", "?")
                    temp = f.get("temperature", "?")
                    precip = f.get("precipitation", 0)
                    weather_text = weather_text + " " + str(time_str) + ":" + str(temp) + "C"
                    if precip > 0:
                        weather_text = weather_text + "+" + str(precip) + "mm"
                    weather_text = weather_text + ","
                weather_text = weather_text.rstrip(",")
        
        weather_text = weather_text + "\n(Use GET_WEATHER tool for full 48h + weekly forecast)"
        return weather_text
    except Exception as e:
        log_error("Weather fetch error: " + str(e), 0)
        return "Weather data not available."


def get_weather_full():
    """Fetch FULL weather data for GET_WEATHER tool.
    
    Returns complete hourly forecast (48h) and weekly overview.
    Called when LLM explicitly requests weather details via GET_WEATHER tool.
    
    Returns:
        Formatted string with full hourly (48h) and weekly forecast
    """
    try:
        # Get current conditions
        weather_state = hass.states.get(WEATHER_ENTITY)
        current_condition = weather_state.state if weather_state else "unknown"
        current_temp = weather_state.attributes.get("temperature", "?") if weather_state else "?"
        humidity = weather_state.attributes.get("humidity", "?") if weather_state else "?"
        wind_speed = weather_state.attributes.get("wind_speed", "?") if weather_state else "?"
        
        weather_text = "=== CURRENT CONDITIONS ===\n"
        weather_text = weather_text + "Condition: " + str(current_condition) + "\n"
        weather_text = weather_text + "Temperature: " + str(current_temp) + "C\n"
        weather_text = weather_text + "Humidity: " + str(humidity) + "%\n"
        weather_text = weather_text + "Wind: " + str(wind_speed) + " km/h\n"
        
        hourly_response = hass.services.call(
            "weather", "get_forecasts",
            {"entity_id": WEATHER_ENTITY, "type": "hourly"},
            blocking=True, return_response=True
        )
        daily_response = hass.services.call(
            "weather", "get_forecasts",
            {"entity_id": WEATHER_ENTITY, "type": "daily"},
            blocking=True, return_response=True
        )
        
        weather_text = weather_text + "\n=== HOURLY FORECAST (48h) ===\n"
        if hourly_response and WEATHER_ENTITY in hourly_response:
            for f in hourly_response[WEATHER_ENTITY].get("forecast", []):
                time_str = format_timestamp(f.get("datetime", ""), '%H:%M %a')
                condition = f.get("condition", "?")
                temp = f.get("temperature", "?")
                precip = f.get("precipitation", 0)
                weather_text = weather_text + str(time_str) + ": " + str(condition) + " (" + str(temp) + "C"
                if precip > 0:
                    weather_text = weather_text + ", " + str(precip) + "mm rain"
                weather_text = weather_text + ")\n"
        
        weather_text = weather_text + "\n=== WEEKLY FORECAST ===\n"
        if daily_response and WEATHER_ENTITY in daily_response:
            for f in daily_response[WEATHER_ENTITY].get("forecast", []):
                day_str = format_timestamp(f.get("datetime", ""), '%A %d.%m.')
                condition = f.get("condition", "?")
                temp_high = f.get("temperature", "?")
                temp_low = f.get("templow", "?")
                precip = f.get("precipitation", 0)
                weather_text = weather_text + str(day_str) + ": " + str(condition) + " (Max: " + str(temp_high) + "C, Min: " + str(temp_low) + "C"
                if precip > 0:
                    weather_text = weather_text + ", " + str(precip) + "mm rain"
                weather_text = weather_text + ")\n"
        
        return weather_text
    except Exception as e:
        log_error("Full weather fetch error: " + str(e), 0)
        return "Full weather data not available."

def collect_calendar():
    """Fetch and format calendar events."""
    try:
        response = hass.services.call(
            "calendar", "get_events",
            {"entity_id": CALENDARS, "duration": {"hours": CALENDAR_LOOKAHEAD_HOURS}},
            blocking=True, return_response=True
        )
        
        calendar_text = "Calendar entries:"
        if response:
            for calendar_entity in response:
                friendly_name = get_attr(calendar_entity, "friendly_name", calendar_entity)
                calendar_text = calendar_text + "\nCalendar '" + str(friendly_name) + "' events for the next " + str(CALENDAR_LOOKAHEAD_HOURS) + " hours:"
                
                events = response[calendar_entity].get("events", [])
                if events:
                    for event in events:
                        summary = event.get("summary", "No title")
                        start = event.get("start", "")
                        end = event.get("end", "")
                        
                        if start:
                            start_str = format_timestamp(start, '%H:%M %d.%m.%Y')
                            end_str = format_timestamp(end, '%H:%M %d.%m.%Y')
                            calendar_text = calendar_text + "\n - Summary: " + str(summary)
                            calendar_text = calendar_text + "\n   Start-End: " + str(start_str) + " to " + str(end_str)
                        else:
                            calendar_text = calendar_text + "\n - Summary: " + str(summary) + " (All Day)"
                        
                        if "description" in event:
                            calendar_text = calendar_text + "\n   Description: " + str(event['description'])
                        if "location" in event:
                            calendar_text = calendar_text + "\n   Location: " + str(event['location'])
                else:
                    calendar_text = calendar_text + "\n - No upcoming events."
        
        return calendar_text
    except Exception as e:
        log_error("Calendar fetch error: " + str(e), 0)
        return "Calendar data not available."

def collect_birthdays():
    """Fetch and format birthday events."""
    try:
        response = hass.services.call(
            "calendar", "get_events",
            {"entity_id": BIRTHDAY_CALENDARS, "duration": {"days": BIRTHDAY_DURATION_DAYS}},
            blocking=True, return_response=True
        )
        
        all_events = []
        if response:
            for calendar_entity in response:
                events = response[calendar_entity].get("events", [])
                all_events.extend(events)
        
        birthday_text = "Upcoming birthdays:"
        if all_events:
            all_events.sort(key=lambda x: x.get("start", ""))
            for event in all_events:
                summary = event.get("summary", "?")
                start = format_timestamp(event.get("start", ""), '%d.%m.')
                birthday_text = birthday_text + "\n - " + str(summary) + " (" + str(start) + ")"
        else:
            birthday_text = birthday_text + "\n - None."
        
        return birthday_text
    except Exception as e:
        log_error("Birthday fetch error: " + str(e), 0)
        return "Birthday data not available."

def collect_tasks():
    """Fetch and format tasks."""
    try:
        response = hass.services.call(
            "todo", "get_items",
            {"entity_id": TASK_LISTS, "status": "needs_action"},
            blocking=True, return_response=True
        )
        
        task_text = "Tasks for today:"
        if response:
            for task_entity in response:
                friendly_name = get_attr(task_entity, "friendly_name", task_entity)
                
                if friendly_name == "Einkaufsliste":
                    items = response[task_entity].get("items", [])
                    task_text = task_text + "\nShopping list: " + str(len(items)) + " items"
                    continue
                
                task_text = task_text + "\nUpcoming tasks on list '" + str(friendly_name) + "':"
                items = response[task_entity].get("items", [])
                
                if items:
                    for task in items:
                        summary = task.get("summary", "?")
                        status = task.get("status", "?")
                        
                        if "due" in task:
                            try:
                                # Parse due date without imports
                                due_str = str(task["due"]).split('T')[0]
                                due_parts = due_str.split('-')
                                current = now()
                                today_str = str(current.year) + "-" + str(current.month).zfill(2) + "-" + str(current.day).zfill(2)
                                today_parts = today_str.split('-')
                                
                                # Simple day difference calculation
                                due_days = int(due_parts[0]) * 365 + int(due_parts[1]) * 30 + int(due_parts[2])
                                today_days = int(today_parts[0]) * 365 + int(today_parts[1]) * 30 + int(today_parts[2])
                                days_diff = due_days - today_days
                                
                                # Note: Using += here is fine since it's within a deeply nested loop
                                # and the string is being built incrementally
                                if days_diff <= 7:
                                    if days_diff == 0:
                                        task_text = task_text + "\n - " + summary + " (" + status + "/due today)"
                                    elif days_diff == 1:
                                        task_text = task_text + "\n - " + summary + " (" + status + "/due tomorrow)"
                                    elif days_diff > 0:
                                        task_text = task_text + "\n - " + summary + " (" + status + "/due in " + str(days_diff) + " days)"
                                    else:
                                        task_text = task_text + "\n - " + summary + " (" + status + "/overdue)"
                            except:
                                task_text = task_text + "\n - " + summary + " (" + status + ")"
                        else:
                            task_text = task_text + "\n - " + summary + " (" + status + ")"
                else:
                    task_text = task_text + "\n - No current tasks."
        
        return task_text
    except Exception as e:
        log_error("Task fetch error: " + str(e), 0)
        return "Task data not available."

def collect_sbahn():
    """Fetch and format public transport departures from all configured stations."""
    if not TRANSPORT_STATIONS:
        return "Public transport: Not configured."
    
    try:
        sbahn_text = "Public transport departures:"
        
        for station in TRANSPORT_STATIONS:
            station_name = station.get("name", station.get("id", "Unknown"))
            entity_id = station.get("entity", "")
            
            sbahn_text = sbahn_text + "\n\nFrom " + station_name + ":"
            
            if not entity_id:
                sbahn_text = sbahn_text + "\n    Not configured"
                continue
            
            state_obj = hass.states.get(entity_id)
            if state_obj and state_obj.attributes:
                departures = state_obj.attributes.get("next_departures", [])
                if departures:
                    for dep in departures[:3]:
                        sbahn_text = sbahn_text + "\n    " + str(dep.get('departure_current', '?'))
                else:
                    sbahn_text = sbahn_text + "\n    No trains"
            else:
                sbahn_text = sbahn_text + "\n    No data"
        
        return sbahn_text
    except Exception as e:
        log_error("Transport fetch error: " + str(e), 0)
        return "Transport data not available."

def collect_sensors():
    """Fetch and format sensor data."""
    try:
        co2 = hass.states.get(CO2_SENSOR)
        co2_value = float(co2.state) if co2 else 0
        
        sensor_text = "Apartment climate:\n - CO2 level: " + str(int(co2_value)) + " ppm"
        if co2_value > 1000:
            sensor_text = sensor_text + " (WARNING: High! Ventilation recommended!)"
        
        return sensor_text
    except Exception as e:
        log_error("Sensor fetch error: " + str(e), 0)
        return "Sensor data not available."

# -------------------------------------------------------
# ROUTINE HINT
# -------------------------------------------------------
def get_routine_hint(hour):
    """Get a hint string for the LLM based on time of day."""
    if 5 <= hour < 10:
        return "Morning routine: Focus on daily overview, weather, important appointments. Be motivating!"
    elif 10 <= hour < 14:
        return "Noon: Short and brief. Only current info."
    elif 14 <= hour < 18:
        return "Afternoon: Reminders, evening planning, check traffic if appointments."
    elif 18 <= hour < 21:
        return "Early evening: Relaxed tone, daily review. NO 'Good night' yet!"
    elif 21 <= hour < 23:
        return "Late evening: Relaxed, preparation for tomorrow. 'Good night' now allowed."
    else:
        return "Night: Minimal. Only become active for real problems."

# -------------------------------------------------------
# INITIALIZATION
# -------------------------------------------------------
# This section runs once at agent startup:
# 1. Get current time using HA's now() built-in
# 2. Collect all context data (weather, calendar, etc.)
# 3. Load user memory (facts and corrections)
# 4. Initialize agent state tracking
# -------------------------------------------------------

log_msg("STARTING AGENT RUN", 0)

# Get current time - try multiple methods
try:
    current_time = datetime.datetime.now()
    current_hour = current_time.hour
    current_time_str = str(current_time.hour).zfill(2) + ":" + str(current_time.minute).zfill(2)
    current_date_str = str(current_time.day).zfill(2) + "." + str(current_time.month).zfill(2) + "." + str(current_time.year)
except:
    try:
        current_time = now()
        current_hour = current_time.hour
        current_time_str = str(current_time.hour).zfill(2) + ":" + str(current_time.minute).zfill(2)
        current_date_str = str(current_time.day).zfill(2) + "." + str(current_time.month).zfill(2) + "." + str(current_time.year)
    except Exception as e:
        log_error("Time functions failed: " + str(e), 1)
        current_hour = 12
        current_time_str = "12:00"
        current_date_str = "unknown"

# Collect all context data
context_weather = collect_weather()
context_calendar = collect_calendar()
context_birthday = collect_birthdays()
context_tasks = collect_tasks()
context_sensors = collect_sensors()
context_background = PERSONAL_BACKGROUND_INFO
context_time = "Current time: " + current_time_str + ", Date: " + current_date_str

log_msg("Data collection complete, time: " + current_time_str, 0)

# Get routine hint for current time
routine_hint = get_routine_hint(current_hour)

memory_facts = get_attr(ENTITY_MEMORY, "learned_facts", "Noch nichts gelernt.")
memory_corrections_raw = get_attr(ENTITY_MEMORY, "correction_log", [])

# Format corrections for better readability in prompt
if memory_corrections_raw and len(memory_corrections_raw) > 0:
    memory_corrections = ""
    for corr in memory_corrections_raw:
        # Try to access as dict, fallback to string
        try:
            text = corr.get("text", str(corr))
            time = corr.get("time", "")
            memory_corrections = memory_corrections + "\n- [" + str(time) + "] " + str(text)
        except:
            memory_corrections = memory_corrections + "\n- " + str(corr)
else:
    memory_corrections = "No corrections."

# Check memory entity size on startup
mem_size, mem_warning, mem_critical = check_attr_size(ENTITY_MEMORY, warn_user=True)
if mem_critical:
    log_warn("Memory entity is almost full (" + str(mem_size) + " bytes). Old facts may need pruning!", 0)

# Consolidated agent state - single source of truth for all agent tracking
# This dictionary is passed to helper functions and modified throughout the run.
# Key fields:
#   history: List of tool calls and results (for LLM context)
#   current_plan: Multi-step plan if PLAN tool was used
#   plan_index: Current step in the plan
#   alert_sent: Prevents multiple alerts in one session
#   draft_count: Tracks DRAFT iterations (max MAX_REVIEW_ITERATIONS)
#   consecutive_errors: For graceful failure after MAX_CONSECUTIVE_ERRORS
agent_state = {
    "history": [],
    "tool_sequence": [],
    "final_message": None,
    "review_passed": False,
    "memory_read": False,
    "alert_sent": False,
    "consecutive_errors": 0,
    "devices_controlled": [],
    "actions_taken": [],
    "current_goal": None,
    "current_plan": [],
    "plan_index": 0,
    "tool_retry_count": {},
    "last_failed_tool": None,
    "suggested_alternatives": [],
    "draft_count": 0,
    "last_draft": None,
    "draft_feedback": [],
    "persona_drafts": [],  # Stores individual persona drafts from DRAFT tool
}

# Aliases for backward compatibility in main loop
agent_history = agent_state["history"]
tool_sequence = agent_state["tool_sequence"]

def enforce_history_limit():
    """Ensure history doesn't exceed maximum length."""
    while len(agent_history) > MAX_HISTORY_LENGTH:
        agent_history.pop(0)

# -------------------------------------------------------
# MAIN LOOP
# -------------------------------------------------------
# The core agent loop:
# 1. Build the full prompt with system instructions, context, and history
# 2. Call the LLM to get the next tool decision
# 3. Parse the response (TOOL / REASON / CONTENT format)
# 4. Execute the tool and record the result
# 5. Check for FINISH or max iterations
#
# Each iteration appends to history, which is included in future prompts
# so the LLM can see what it has already done.
# -------------------------------------------------------

for i in range(MAX_ITERATIONS):
    iter_num = i + 1
    
    # Check for too many consecutive errors
    if agent_state["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
        log_error("Too many consecutive errors (" + str(agent_state['consecutive_errors']) + "), aborting", iter_num)
        agent_state["final_message"] = "The LLM produced only invalid or incomprehensible responses. Aborting."
        break
    
    # Analyze context for autonomous suggestions (initialize first!)
    auto_suggestions = []
    
    # CO2 check
    try:
        co2_state = hass.states.get(CO2_SENSOR)
        if co2_state:
            co2_val = float(co2_state.state)
            if co2_val > 1000:
                auto_suggestions.append("HIGH CO2 VALUE: " + str(int(co2_val)) + " ppm! Ventilation recommended.")
    except:
        pass
    
    # Check for upcoming calendar events
    try:
        if "calendar" in context_calendar.lower() and current_hour >= 6 and current_hour <= 22:
            # Extract if there's an event soon (simple heuristic)
            if any(x in context_calendar for x in ["08:", "09:", "10:", "11:", "12:"]):
                auto_suggestions.append("Appointments today - check S-Bahn times?")
    except:
        pass
    
    # Smart recovery: If we're past halfway and haven't made progress, suggest finishing
    if iter_num > MAX_ITERATIONS // 2 and not agent_state["actions_taken"] and not agent_state["current_plan"]:
        auto_suggestions.append("Already " + str(iter_num) + " iterations without action. Create a PLAN or go directly to FINISH!")
    
    # If we have a plan and completed it, strongly suggest FINISH
    if agent_state["current_plan"] and agent_state["plan_index"] >= len(agent_state["current_plan"]):
        auto_suggestions.insert(0, "PLAN COMPLETED! Use FINISH with a summary now.")
    
    # Build history text
    history_text = ""
    for step in agent_history:
        t_call = str(step.get('tool_call')).replace("<", "(").replace(">", ")")
        t_reason = str(step.get('reason', '')).replace("<", "(").replace(">", ")")[:REASON_PREVIEW_LENGTH]
        res = str(step.get('result')).replace("<", "(").replace(">", ")")
        history_text = history_text + "[Tool: " + t_call + " | Reason: " + t_reason + " | Result: " + res + "]\n"
    
    # Build status section with autonomous context
    plan_status = ""
    current_plan = agent_state["current_plan"]
    plan_index = agent_state["plan_index"]
    if current_plan:
        plan_status = "\n    ACTIVE PLAN (" + str(plan_index) + "/" + str(len(current_plan)) + " completed):"
        for idx, step in enumerate(current_plan):
            if idx < plan_index:
                plan_status = plan_status + "\n      [done] " + str(idx+1) + ". " + step
            elif idx == plan_index:
                plan_status = plan_status + "\n      > " + str(idx+1) + ". " + step + " <- EXECUTE NOW!"
            else:
                plan_status = plan_status + "\n      [ ] " + str(idx+1) + ". " + step
        
        if plan_index >= len(current_plan):
            plan_status = plan_status + "\n    ALL STEPS COMPLETED -> Now FINISH!"
        else:
            plan_status = plan_status + "\n    \n    Execute step " + str(plan_index+1) + " - do NOT create another PLAN!"
    
    retry_info = ""
    if agent_state["last_failed_tool"] and agent_state["suggested_alternatives"]:
        retry_info = "\n    " + agent_state['last_failed_tool'] + " failed. Alternatives: " + ", ".join(agent_state['suggested_alternatives'])
    
    devices_str = ", ".join(agent_state['devices_controlled']) if agent_state['devices_controlled'] else "None"
    actions_str = ", ".join(agent_state['actions_taken']) if agent_state['actions_taken'] else "None"
    auto_sugg_str = "\n".join(auto_suggestions) if auto_suggestions else "No urgent actions detected."
    
    status_info = """Iteration: """ + str(iter_num) + "/" + str(MAX_ITERATIONS) + """
    Alert Sent: """ + str(agent_state['alert_sent']) + """
    Memory Read: """ + str(agent_state['memory_read']) + """
    Devices Controlled: """ + devices_str + """
    Actions Taken: """ + actions_str + plan_status + retry_info + """
    
    """ + routine_hint + """
    
    AUTONOMOUS ANALYSIS:
    """ + auto_sugg_str

    # Inject personal settings into system prompt
    system_prompt_with_settings = SYSTEM_PROMPT.replace("{LANGUAGE}", RESPONSE_LANGUAGE).replace("{USER_NAME}", USER_NAME)

    full_prompt = """""" + system_prompt_with_settings + """
    
    <STATUS>
    """ + status_info + """
    </STATUS>

    <CONTEXT>
    Time: """ + context_time + """
    Weather: """ + context_weather + """
    Calendar: """ + context_calendar + """
    Tasks: """ + context_tasks + """
    Birthdays: """ + context_birthday + """
    Sensors: """ + context_sensors + """
    Background: """ + context_background + """
    </CONTEXT>
    
    <MEMORY>
    Learned Facts: """ + memory_facts + """
    
    USER CORRECTIONS:
    """ + memory_corrections + """
    </MEMORY>

    <HISTORY>
    """ + history_text + """
    </HISTORY>

    Next step? (TOOL: ...)
    """

    try:
        service_data = {
            "entity_id": LLM_ENTITY,
            "task_name": "Agent Step " + str(iter_num),
            "instructions": full_prompt
        }
        
        # In test mode, log the complete LLM prompt
        if TOOL_TEST_MODE:
            log_debug("TEST MODE - FULL LLM PROMPT START ---", iter_num)
            # Split prompt into chunks for logging (HA log has size limits)
            prompt_lines = full_prompt.split("\n")
            for line in prompt_lines:
                if line.strip():
                    log_debug("PROMPT: " + line[:500], iter_num)
            log_debug("TEST MODE - FULL LLM PROMPT END ---", iter_num)
        
        try:
            response = hass.services.call("ai_task", "generate_data", service_data, blocking=True, return_response=True)
            raw_output = str(response["data"]) if response and "data" in response else ""
            
            # In test mode, log the complete LLM response
            if TOOL_TEST_MODE:
                log_debug("TEST MODE - LLM RESPONSE: " + raw_output[:1000], iter_num)
        except Exception as llm_err:
            log_error("LLM Service Failed: " + str(llm_err), iter_num)
            new_step = {"tool_call": "ERROR", "reason": "", "result": "LLM Service Error: " + str(llm_err)}
            agent_history.append(new_step)
            agent_state["consecutive_errors"] = agent_state["consecutive_errors"] + 1
            continue

        decision = parse_llm_text(raw_output)
        tool = decision.get("tool", "ERROR")
        reason = decision.get("reason", "")
        content = decision.get("content", "")
        
        # --- TOOL TEST MODE OVERRIDE ---
        # If enabled, ignore LLM decision and force test sequence
        if TOOL_TEST_MODE:
            test_sequence = ["PLAN", "READ_MEMORY", "GET_ENTITY_STATE", "GET_SBAHN", 
                           "GET_WEATHER", "SEARCH_WEB", "CALCULATE", "CONTROL_DEVICE", 
                           "SAVE_FACT", "URGENT_ALERT", "DRAFT", "FINISH"]
            if iter_num <= len(test_sequence):
                tool = test_sequence[iter_num - 1]
                content = TOOL_TEST_DATA.get(tool, "")
                reason = "TOOL_TEST_MODE: Testing " + tool
                log_debug("TEST MODE: Forcing tool " + tool, iter_num)
            else:
                tool = "FINISH"
                content = "Tool test complete!"
                reason = "TOOL_TEST_MODE: All tools tested"
        
        # Log with preview
        content_preview = content[:LOG_CONTENT_PREVIEW] + "..." if len(content) > LOG_CONTENT_PREVIEW else content
        log_msg("TOOL: " + tool + " | REASON: " + reason[:40] + " | CONTENT: " + content_preview, iter_num)
        
        new_step = {"tool_call": tool, "reason": reason, "result": "..."}
        
        if tool == "ERROR":
            agent_state["consecutive_errors"] = agent_state["consecutive_errors"] + 1
            new_step["result"] = "Could not parse tool. Use exact format: TOOL: [NAME]"
            agent_history.append(new_step)
            continue
        else:
            agent_state["consecutive_errors"] = 0  # Reset on successful parse
            tool_sequence.append(tool)
        
        # ---------------- TOOL LOGIC ----------------
        # Each tool is handled by its own elif branch.
        # Common patterns:
        #   1. Validate input (content not empty, format correct)
        #   2. Perform the action (may involve HA service calls)
        #   3. Build result message
        #   4. Advance plan if applicable
        #   5. Append to history and enforce limit
        #   6. Clear or set retry state as appropriate
        # ------------------------------------------------
        
        if tool == "READ_MEMORY":
            if agent_state["memory_read"]:
                new_step["result"] = "Memory already loaded. Use the info you have. What action will you take next?"
            else:
                log_debug("Memory Facts: " + str(memory_facts)[:100], iter_num)
                facts_preview = memory_facts[:MEMORY_FACTS_PREVIEW] if len(memory_facts) > MEMORY_FACTS_PREVIEW else memory_facts
                corrections_preview = memory_corrections[:MEMORY_CORRECTIONS_PREVIEW] if len(memory_corrections) > MEMORY_CORRECTIONS_PREVIEW else memory_corrections
                new_step["result"] = "Memory loaded.\nFacts: " + facts_preview + "\nCorrections: " + corrections_preview + "\n\nNow analyze context and decide: What actions are needed?"
                agent_state["memory_read"] = True
                agent_state["actions_taken"].append("Memory read")
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "PLAN":
            # Check if there's already an active plan
            current_plan = agent_state["current_plan"]
            plan_index = agent_state["plan_index"]
            if current_plan and plan_index < len(current_plan):
                remaining_steps = len(current_plan) - plan_index
                result_msg = "PLAN ALREADY ACTIVE! You have " + str(remaining_steps) + " steps remaining:\n"
                for idx in range(plan_index, len(current_plan)):
                    marker = "> " if idx == plan_index else "  "
                    result_msg = result_msg + marker + str(idx+1) + ". " + current_plan[idx] + "\n"
                result_msg = result_msg + "\nExecute current step or use FINISH if done. No new plan needed!"
                new_step["result"] = result_msg
            elif not content:
                new_step["result"] = "Error: No plan provided. Use CONTENT to list steps like: 1. Check X | 2. Do Y | 3. Finish"
            else:
                # Use extracted helper function
                new_plan = parse_plan_content(content)
                
                if new_plan:
                    agent_state["current_plan"] = new_plan
                    agent_state["plan_index"] = 0
                    log_debug("PLAN created with " + str(len(new_plan)) + " steps: " + str(new_plan), iter_num)
                    agent_state["actions_taken"].append("Plan: " + str(len(new_plan)) + " steps")
                    steps_list = ""
                    for i, s in enumerate(new_plan):
                        steps_list = steps_list + "\n  " + str(i+1) + ". " + s
                    new_step["result"] = "Plan created with " + str(len(new_plan)) + " steps:" + steps_list + "\n\n> Start now with step 1: " + new_plan[0] + "\n\nIMPORTANT: Execute the first step with the appropriate tool now - NOT another PLAN!"
                else:
                    new_step["result"] = "Error: Could not parse plan steps. Use format: 1. Step one | 2. Step two"
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "SEARCH_WEB":
            if not content:
                new_step["result"] = "Error: No search query provided in CONTENT."
            else:
                try:
                    safe_query = sanitize_input(content)
                    if len(safe_query) < 3:
                        new_step["result"] = "Error: Search query too short."
                    else:
                        search_res = hass.services.call(
                            "shell_command", "agent_search_web", {"q": safe_query}, 
                            blocking=True, return_response=True
                        )
                        if search_res and search_res.get("returncode") == 0:
                            raw_json = str(search_res["stdout"])
                            snippet = raw_json[:MAX_WEB_RESULT_LENGTH]
                            if len(raw_json) > MAX_WEB_RESULT_LENGTH: 
                                snippet = snippet + "...(truncated)"
                            new_step["result"] = "WEB RESULTS: " + snippet
                            clear_retry_state(agent_state)
                        else:
                            error_info = search_res.get("stderr", "Unknown error") if search_res else "No response"
                            new_step["result"] = "Search failed: " + str(error_info)[:200]
                            new_step["result"] = new_step["result"] + set_retry_state(agent_state, "SEARCH_WEB")
                        
                        # Always advance plan after SEARCH_WEB attempt
                        new_step["result"] = new_step["result"] + advance_plan(agent_state)
                except Exception as e:
                    new_step["result"] = "Search Exception: " + str(e)
                    set_retry_state(agent_state, "SEARCH_WEB")
                    advance_plan(agent_state)
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "URGENT_ALERT":
            if agent_state["alert_sent"]:
                new_step["result"] = "STOP: Alert already sent this session. Cannot send another."
            elif not content:
                new_step["result"] = "Error: No alert message provided in CONTENT."
            else:
                log_warn("VERIFYING ALERT...", iter_num)
                verify_prompt = """<SYSTEM>
                ALERT VERIFICATION MODE.
                Proposed Alert: """ + content + """
                Current Sensor Data: """ + context_sensors + """
                
                RULES:
                - CO2 alert: Only if sensor shows > 1000 ppm
                - Storm alert: Only if weather data confirms extremely dangerous conditions
                - Intrusion alert: Only if motion/door sensors triggered unexpectedly when nobody home
                - Fire/Smoke alert: Only if smoke detector triggered
                
                Is this alert TRULY CRITICAL and VERIFIED by sensor data?
                Answer ONLY: YES or NO
                </SYSTEM>"""
                
                try:
                    verify_call = hass.services.call(
                        "ai_task", "generate_data", 
                        {"entity_id": LLM_ENTITY, "task_name": "Verify Alert", "instructions": verify_prompt},
                        blocking=True, return_response=True
                    )
                    verify_res = str(verify_call.get("data", "")).strip().upper()
                    
                    if "YES" in verify_res:
                        try:
                            if DRY_RUN_MODE:
                                hass.services.call("notify", NOTIFY_SERVICE, {
                                    "title": "DRY RUN: Alert would be sent",
                                    "message": "ALERT (dry run): " + content
                                })
                                new_step["result"] = "DRY RUN - Alert would be sent: " + content
                            else:
                                hass.services.call("notify", NOTIFY_SERVICE, {
                                    "message": "ALARM: " + content, 
                                    "title": "Urgent Alert!",
                                    "data": {"priority": "high", "channel": "alarm_stream", "ttl": 0} 
                                })
                                new_step["result"] = "ALERT VERIFIED AND SENT!"
                            agent_state["alert_sent"] = True
                        except Exception as e:
                            new_step["result"] = "Alert Send Failed: " + str(e)
                    else:
                        new_step["result"] = "ALERT BLOCKED: Verification failed. Sensor data does not confirm emergency."
                except Exception as e:
                    new_step["result"] = "Alert Verification Failed: " + str(e)
            
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "SAVE_FACT":
            if not content:
                new_step["result"] = "Error: No fact provided in CONTENT."
            elif len(content) > MAX_FACT_LENGTH:
                new_step["result"] = "Error: Fact too long (" + str(len(content)) + " chars, max " + str(MAX_FACT_LENGTH) + ")."
            elif is_fact_blocked(content):
                new_step["result"] = "BLOCKED: Cannot save transient/sensor data as permanent facts. Only save personal preferences, names, important dates, etc."
            else:
                # Check if memory is approaching size limit
                mem_size, mem_warning, mem_critical = check_attr_size(ENTITY_MEMORY, warn_user=False)
                # Estimate size: ~1.5x len for UTF-8 German text with umlauts
                new_fact_size = len(content) * 2 + 10
                
                if mem_size + new_fact_size >= MAX_ATTR_SIZE - 500:
                    new_step["result"] = "BLOCKED: Memory storage is full (" + str(mem_size) + " bytes). Cannot save new facts until old ones are cleared."
                elif mem_warning:
                    hass.bus.fire(EVENT_MEMORY, {"new_fact": content})
                    new_step["result"] = "Fact saved: '" + content + "' (WARNING: Memory " + str(mem_size*100//MAX_ATTR_SIZE) + "% full)"
                else:
                    hass.bus.fire(EVENT_MEMORY, {"new_fact": content})
                    new_step["result"] = "Fact saved: '" + content + "'"
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "CONTROL_DEVICE":
            if not content:
                new_step["result"] = "Error: No device command provided. Use format: entity_id|action|[value]"
            else:
                parts = content.split("|")
                if len(parts) < 2:
                    new_step["result"] = "Error: Invalid format. Use: entity_id|action|[value]"
                else:
                    entity_id = validate_entity_id(parts[0])
                    action = parts[1].strip().lower()
                    value_part = parts[2].strip() if len(parts) > 2 else None
                    
                    if not entity_id:
                        new_step["result"] = "Error: Invalid or disallowed entity_id: " + parts[0]
                    elif action not in ["turn_on", "turn_off", "toggle", "set_value"]:
                        # Check if they're trying to read state via CONTROL_DEVICE
                        if action in ["get_state", "read", "status", "check"]:
                            new_step["result"] = "Error: '" + action + "' is not a CONTROL_DEVICE action. To READ state, use GET_ENTITY_STATE with CONTENT: " + parts[0]
                        else:
                            new_step["result"] = "Error: Unknown action '" + action + "'. Valid actions: turn_on, turn_off, toggle, set_value. To READ state use GET_ENTITY_STATE."
                    else:
                        # Get current plan step for context
                        current_plan = agent_state["current_plan"]
                        plan_index = agent_state["plan_index"]
                        current_plan_step = current_plan[plan_index] if current_plan and plan_index < len(current_plan) else ""
                        
                        # Validate the action makes sense
                        is_valid, validation_error = validate_device_control(entity_id, action, reason, current_plan_step)
                        
                        if not is_valid:
                            new_step["result"] = "BLOCKED: " + str(validation_error) + " Consider if this action is really needed."
                            new_step["result"] = new_step["result"] + advance_plan(agent_state)
                            agent_history.append(new_step)
                            continue
                        
                        try:
                            domain = entity_id.split(".")[0]
                            service_domain = domain if domain in ["light", "switch", "fan", "cover", "climate", "media_player", "vacuum", "lock"] else "homeassistant"
                            
                            service_data_call = {"entity_id": entity_id}
                            
                            # Parse value parameters (e.g., brightness=80)
                            if value_part:
                                for param in value_part.split(","):
                                    if "=" in param:
                                        key, val = param.split("=", 1)
                                        key = key.strip()
                                        val = val.strip()
                                        try:
                                            if "." in val:
                                                service_data_call[key] = float(val)
                                            else:
                                                service_data_call[key] = int(val)
                                        except ValueError:
                                            service_data_call[key] = val
                            
                            action_desc = entity_id + " -> " + action + (" with " + value_part if value_part else "")
                            
                            if DRY_RUN_MODE:
                                # DRY RUN: Send notification instead of actual control
                                notify_dry_run("CONTROL_DEVICE: " + action_desc)
                                agent_state["devices_controlled"].append(entity_id + ":" + action + "(DRY)")
                                agent_state["actions_taken"].append("🔧 " + action_desc)
                                result_msg = "DRY RUN - Would execute: " + action_desc + ". Action logged."
                                clear_retry_state(agent_state)
                                result_msg = result_msg + advance_plan(agent_state)
                                new_step["result"] = result_msg
                            else:
                                # PRODUCTION MODE: Actually control the device
                                if action == "set_value":
                                    if domain == "input_number" and "value" in service_data_call:
                                        hass.services.call("input_number", "set_value", service_data_call)
                                    elif domain == "input_boolean":
                                        hass.services.call("input_boolean", "turn_on" if value_part else "turn_off", service_data_call)
                                    else:
                                        new_step["result"] = "Error: set_value not supported for domain " + domain
                                        agent_history.append(new_step)
                                        enforce_history_limit()
                                        continue
                                else:
                                    hass.services.call(service_domain, action, service_data_call)
                                
                                agent_state["devices_controlled"].append(entity_id + ":" + action)
                                agent_state["actions_taken"].append("Controlled: " + action_desc)
                                result_msg = "SUCCESS: " + action_desc + "."
                                clear_retry_state(agent_state)
                                result_msg = result_msg + advance_plan(agent_state)
                                new_step["result"] = result_msg
                        except Exception as e:
                            new_step["result"] = "Device Control Failed: " + str(e)
                            new_step["result"] = new_step["result"] + set_retry_state(agent_state, "CONTROL_DEVICE")
                            new_step["result"] = new_step["result"] + advance_plan(agent_state)
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "GET_ENTITY_STATE":
            if not content:
                new_step["result"] = "Error: No entity_id provided in CONTENT."
            else:
                entity_id = validate_entity_id(content)
                if not entity_id:
                    new_step["result"] = "Error: Invalid entity_id format: " + content
                    set_retry_state(agent_state, "GET_ENTITY_STATE")
                else:
                    state_info = get_state(entity_id)
                    if state_info:
                        attrs_str = str(state_info["attributes"])
                        if len(attrs_str) > ATTRS_PREVIEW_LENGTH:
                            attrs_str = attrs_str[:ATTRS_PREVIEW_LENGTH] + "..."
                        # Add actionable hints based on state
                        action_hint = ""
                        state_val = state_info['state'].lower()
                        if state_val == "on" and "light" in entity_id:
                            action_hint = " Light is ON. Turn off if not needed?"
                        elif state_val == "open" and ("window" in entity_id or "fenster" in entity_id):
                            action_hint = " Window is OPEN. Check weather/CO2."
                        new_step["result"] = "State: " + entity_id + " = " + state_info['state'] + " | Attrs: " + attrs_str + action_hint
                        agent_state["actions_taken"].append("Checked " + entity_id)
                        clear_retry_state(agent_state)
                    else:
                        new_step["result"] = "Error: Entity '" + entity_id + "' not found."
                        set_retry_state(agent_state, "GET_ENTITY_STATE")
                        domain = entity_id.split(".")[0] if "." in entity_id else ""
                        new_step["result"] = new_step["result"] + " Try a different " + domain + " entity, or continue."
                    
                    # Always advance plan
                    new_step["result"] = new_step["result"] + advance_plan(agent_state)
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "GET_SBAHN":
            direction = content.strip().lower() if content else ""
            
            if not TRANSPORT_STATIONS:
                new_step["result"] = "Error: No transport stations configured."
                agent_history.append(new_step)
                enforce_history_limit()
                continue
            
            # Find matching station by id or alias
            matched_station = None
            
            if not direction:
                # Default to first station
                matched_station = TRANSPORT_STATIONS[0]
            else:
                for station in TRANSPORT_STATIONS:
                    # Check if direction matches id
                    if direction == station.get("id", "").lower():
                        matched_station = station
                        break
                    # Check if direction matches any alias
                    aliases = station.get("aliases", [])
                    if direction in [a.lower() for a in aliases]:
                        matched_station = station
                        break
            
            if not matched_station:
                # Build list of valid options for error message
                valid_options = []
                for station in TRANSPORT_STATIONS:
                    valid_options.append(station.get("id", "?"))
                new_step["result"] = "Error: Unknown station '" + direction + "'. Valid options: " + ", ".join(valid_options)
                agent_history.append(new_step)
                enforce_history_limit()
                continue
            
            try:
                station_name = matched_station.get("name", matched_station.get("id", "Unknown"))
                sbahn_entity = matched_station.get("entity", "")
                sbahn_text = "Departures from " + station_name + ":"
                
                sbahn_state = hass.states.get(sbahn_entity)
                if sbahn_state and sbahn_state.attributes:
                    departures = sbahn_state.attributes.get("next_departures", [])
                    if departures:
                        for dep in departures[:3]:
                            dep_time = dep.get('departure_current', '?')
                            sbahn_text = sbahn_text + "\n  - " + str(dep_time)
                    else:
                        sbahn_text = sbahn_text + "\n  No trains available"
                else:
                    sbahn_text = sbahn_text + "\n  No data available"
                
                new_step["result"] = sbahn_text
                agent_state["actions_taken"].append("Checked transport (" + station_name + ")")
                new_step["result"] = new_step["result"] + advance_plan(agent_state)
            except Exception as e:
                new_step["result"] = "Transport fetch error: " + str(e)
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "GET_WEATHER":
            # Fetch full weather data (48h hourly + weekly forecast)
            try:
                weather_data = get_weather_full()
                new_step["result"] = weather_data
                agent_state["actions_taken"].append("Fetched full weather forecast")
                new_step["result"] = new_step["result"] + advance_plan(agent_state)
            except Exception as e:
                new_step["result"] = "Weather fetch error: " + str(e)
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "CALCULATE":
            if not content:
                new_step["result"] = "Error: No expression provided in CONTENT."
            else:
                result, error = safe_calculate(content)
                if error:
                    new_step["result"] = "Calculation Error: " + str(error)
                    set_retry_state(agent_state, "CALCULATE")
                else:
                    if result == int(result):
                        result_str = str(int(result))
                    else:
                        # Format to 4 decimal places and strip trailing zeros
                        result_str = str(round(result, 4))
                        if "." in result_str:
                            result_str = result_str.rstrip("0").rstrip(".")
                    new_step["result"] = "Result: " + content + " = " + result_str
                    clear_retry_state(agent_state)
                
                # Always advance plan
                new_step["result"] = new_step["result"] + advance_plan(agent_state)
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "REVIEW":
            # REVIEW is now optional - just validate and give feedback
            if not content:
                new_step["result"] = "Error: No draft provided in CONTENT."
            else:
                issues = validate_message(content)
                if issues:
                    new_step["result"] = "Issues found: " + "; ".join(issues) + ". Consider fixing before FINISH."
                    agent_state["review_passed"] = False
                    log_msg("REVIEW: Issues - " + "; ".join(issues), iter_num)
                else:
                    new_step["result"] = "Looks good (" + str(len(content)) + " chars). Ready to FINISH."
                    log_msg("REVIEW: Passed (" + str(len(content)) + " chars)", iter_num)
                    agent_state["review_passed"] = True
            agent_history.append(new_step)
            enforce_history_limit()
            
        elif tool == "DRAFT":
            if not content:
                new_step["result"] = "Error: No topic/key points provided in CONTENT."
            else:
                agent_state["draft_count"] = agent_state["draft_count"] + 1
                
                # Build context from RAW COLLECTED DATA (not agent history which may have LLM interpretations)
                context_parts = []
                
                # Add raw collected data as source of truth
                context_parts.append("TIME: " + current_time_str + ", DATE: " + current_date_str)
                if context_weather:
                    context_parts.append("WEATHER: " + str(context_weather)[:150])
                if context_calendar:
                    context_parts.append("CALENDAR: " + str(context_calendar)[:150])
                if context_birthday:
                    context_parts.append("BIRTHDAYS: " + str(context_birthday)[:100])
                if context_tasks:
                    context_parts.append("TASKS: " + str(context_tasks)[:100])
                if context_sensors:
                    context_parts.append("SENSORS: " + str(context_sensors)[:150])
                
                # Add memory corrections as STRICT RULES
                if memory_corrections and memory_corrections != "No corrections.":
                    context_parts.append("USER RULES (MUST FOLLOW): " + memory_corrections[:200])
                
                # Add tool results from history (but only raw data, not LLM interpretations)
                for h in agent_history[-5:]:
                    tool_used = h.get("tool_call", "")
                    if tool_used in ["GET_ENTITY_STATE", "GET_WEATHER", "GET_SBAHN", "READ_MEMORY", "CALCULATE"]:
                        if h.get("result") and "Error" not in h.get("result", ""):
                            context_parts.append(tool_used + ": " + h.get("result", "")[:100])
                
                context_summary = "\n".join(context_parts) if context_parts else "General greeting/update"
                
                # Generate persona drafts, fact-check, and merge
                log_msg("DRAFT: Generating " + str(NUM_DRAFT_PERSONAS) + " persona drafts...", iter_num)
                merged_draft, persona_drafts, merge_notes, fact_check_result = generate_persona_drafts(
                    content, 
                    context_summary, 
                    USER_NAME, 
                    RESPONSE_LANGUAGE
                )
                
                agent_state["last_draft"] = merged_draft
                agent_state["persona_drafts"] = persona_drafts  # Store for reference
                
                # Build result with persona previews
                result_text = "=== PERSONA DRAFTS GENERATED ===\n"
                for pd in persona_drafts:
                    preview = pd["draft"][:80] + "..." if len(pd["draft"]) > 80 else pd["draft"]
                    result_text = result_text + "\n[" + pd["persona"] + "]: " + preview
                
                # Show fact-check result
                result_text = result_text + "\n\n=== FACT CHECK ===\n"
                if fact_check_result:
                    result_text = result_text + fact_check_result
                else:
                    result_text = result_text + "No fact check performed"
                
                result_text = result_text + "\n\n=== MERGED DRAFT ===\n" + merged_draft
                
                if merge_notes:
                    result_text = result_text + "\n\n[Merge notes: " + merge_notes[:100] + "]"
                
                # Validate the merged draft
                issues = validate_message(merged_draft)
                
                # Verify language
                lang_ok = True
                if not issues:
                    lang_ok, lang_feedback = verify_language(merged_draft, RESPONSE_LANGUAGE)
                    if not lang_ok:
                        issues.append(lang_feedback)
                
                result_text = result_text + "\n\n--- REVIEW ---\n"
                result_text = result_text + "Length: " + str(len(merged_draft)) + " chars\n"
                
                if issues:
                    result_text = result_text + "Issues: " + "; ".join(issues) + "\n"
                    result_text = result_text + "Action: Edit the merged draft and use DRAFT again, or use FINISH if acceptable."
                    agent_state["review_passed"] = False
                    log_msg("DRAFT REVIEW: Issues - " + "; ".join(issues), iter_num)
                else:
                    result_text = result_text + "Status: Ready to send!\n"
                    result_text = result_text + "Action: Use FINISH with the merged draft (copy it exactly or edit slightly)."
                    agent_state["review_passed"] = True
                    log_msg("DRAFT REVIEW: Passed (" + str(len(merged_draft)) + " chars, " + RESPONSE_LANGUAGE + ")", iter_num)
                
                new_step["result"] = result_text
                
            agent_history.append(new_step)
            enforce_history_limit()

        elif tool == "FINISH":
            if not content:
                new_step["result"] = "Error: No message provided in CONTENT."
                agent_history.append(new_step)
                enforce_history_limit()
            else:
                # Mark plan as completed when finishing
                if agent_state["current_plan"]:
                    agent_state["plan_index"] = len(agent_state["current_plan"])
                
                # Auto-validate and fix common issues
                issues = validate_message(content)
                if issues:
                    # Try to auto-fix length issue
                    if len(content) > MAX_MESSAGE_LENGTH:
                        content = content[:MAX_MESSAGE_LENGTH-3] + "..."
                        log_warn("Auto-truncated message to " + str(MAX_MESSAGE_LENGTH) + " chars", iter_num)
                    
                    # Check for remaining critical issues
                    remaining_issues = []
                    for issue in issues:
                        if "HTML" in issue or "Markdown" in issue:
                            remaining_issues.append(issue)
                    if remaining_issues:
                        new_step["result"] = "Auto-fix failed for: " + str(remaining_issues) + ". Fix formatting."
                        agent_history.append(new_step)
                        enforce_history_limit()
                        continue
                
                # Verify language before sending (if not already verified via DRAFT)
                if not agent_state["review_passed"]:
                    lang_ok, lang_feedback = verify_language(content, RESPONSE_LANGUAGE)
                    if not lang_ok:
                        new_step["result"] = "LANGUAGE ERROR: " + lang_feedback + " Use DRAFT to revise."
                        agent_history.append(new_step)
                        enforce_history_limit()
                        continue
                
                # Log autonomous actions taken
                if agent_state["actions_taken"]:
                    log_debug("Autonomous actions this run: " + str(agent_state["actions_taken"]), iter_num)
                
                agent_state["final_message"] = content
                log_msg("FINISH: " + str(len(content)) + " chars (" + RESPONSE_LANGUAGE + ")", iter_num)
                break
            
        else:
            new_step["result"] = "Unknown Tool: '" + tool + "'. Available: PLAN, READ_MEMORY, SEARCH_WEB, URGENT_ALERT, SAVE_FACT, CONTROL_DEVICE, GET_ENTITY_STATE, GET_SBAHN, GET_WEATHER, CALCULATE, DRAFT, REVIEW, FINISH"
            agent_history.append(new_step)
            enforce_history_limit()
            agent_state["consecutive_errors"] = agent_state["consecutive_errors"] + 1

    except Exception as e:
        log_error("CRITICAL ERROR in iteration " + str(iter_num) + ": " + str(e), iter_num)
        agent_state["consecutive_errors"] = agent_state["consecutive_errors"] + 1
        if agent_state["consecutive_errors"] >= MAX_CONSECUTIVE_ERRORS:
            agent_state["final_message"] = "Agent encountered repeated errors. Last error: " + str(e)
            break

# -------------------------------------------------------
# OUTPUT / CLEANUP
# -------------------------------------------------------
# After the main loop exits (via FINISH or max iterations):
# 1. Log the tool sequence for debugging
# 2. Fire event to notify user with final message
# 3. Update memory entity with run status
# -------------------------------------------------------

tools_str = ",".join(tool_sequence)
current_plan = agent_state["current_plan"]
plan_index = agent_state["plan_index"]
plan_str = " -> ".join(current_plan) if current_plan else "No plan"
log_msg("Tool sequence: " + tools_str, 99)
if current_plan:
    log_msg("Plan: " + plan_str + " (" + str(plan_index) + "/" + str(len(current_plan)) + " steps completed)", 99)
else:
    log_msg("No plan used", 99)

final_message = agent_state["final_message"]
if final_message:
    final_message = final_message.strip()
    if len(final_message) > MAX_REVIEW_LENGTH:
        final_message = final_message[:MAX_MESSAGE_LENGTH] + "..."
    
    hass.bus.fire(EVENT_NOTIFY, {"payload": final_message})
    hass.bus.fire(EVENT_MEMORY, {
        "agent_status": "DONE",
        "tools_used": tools_str,
        "iterations": iter_num
    })
else:
    error_msg = "Agent finished without result after " + str(iter_num) + "/" + str(MAX_ITERATIONS) + " steps. Tools: " + tools_str
    hass.bus.fire(EVENT_NOTIFY, {"payload": error_msg})
    hass.bus.fire(EVENT_MEMORY, {
        "agent_status": "TIMEOUT",
        "tools_used": tools_str,
        "iterations": iter_num
    })
    log_error(error_msg, 99)

log_msg("AGENT RUN COMPLETE.", 99)
