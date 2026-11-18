# ash_e_msgs/TargetFeedback  (spec 3.6). Published by out-of-scope nodes (nudge UI / drive).
std_msgs/Header header
uint32 track_id
uint8  RESULT_DONE=1
uint8  RESULT_REFUSED=2
uint8  RESULT_ABORTED=3
uint8  RESULT_UNREACHABLE=4
uint8  result
