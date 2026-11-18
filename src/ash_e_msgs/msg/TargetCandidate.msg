# ash_e_msgs/TargetCandidate  (spec 3.4). Mirrors ash_e_core.types.TargetCandidate.
uint32  track_id
uint8   state
float32 score                 # 0..1 (computed value is kept even when eligible=false)
float32 s_state
float32 s_dist
float32 s_conf
float32 s_center
float32 s_stay
float32 distance_m
float32 bearing_rad
bool    eligible
uint8   ineligible_reason     # core Ineligible: OK=0 NOT_CONFIRMED=1 LOW_CONFIDENCE=2 OUT_OF_RANGE=3 COOLDOWN=4
float32 cooldown_remaining_s
