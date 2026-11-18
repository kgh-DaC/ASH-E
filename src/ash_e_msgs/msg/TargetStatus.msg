# ash_e_msgs/TargetStatus  (spec 3.5). Mirrors ash_e_core.types.TargetStatus.
std_msgs/Header header        # stamp = evaluation time, frame_id = frame_id of the input detections
uint8 MODE_IDLE=0
uint8 MODE_TRACKING=1
uint8 EVENT_NONE=0
uint8 EVENT_ACQUIRED=1
uint8 EVENT_SWITCHED_BETTER=2
uint8 EVENT_LOST_TIMEOUT=3
uint8 EVENT_OUT_OF_RANGE=4
uint8 EVENT_STATE_CLEARED=5
uint8 EVENT_INPUT_TIMEOUT=6
uint8 EVENT_FEEDBACK_RELEASED=7

uint8   mode
bool    has_target
uint32  target_id             # 0 if none
bool    target_visible        # whether the target was seen in this input (false while waiting in LOST)
uint8   target_state
float32 target_score
geometry_msgs/Point target_position   # last observed position
float32 target_distance_m
float32 target_bearing_rad
uint8   distance_source
float32 tracking_duration_s
bool    locked                # lock during the nudge interaction
uint8   last_event            # event raised in this evaluation (EVENT_NONE if none)
uint32  previous_target_id    # previous target id (0 if none)
TargetCandidate[] ranking     # score descending, includes ineligible candidates
