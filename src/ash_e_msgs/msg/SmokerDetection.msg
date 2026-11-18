# ash_e_msgs/SmokerDetection  (spec 3.2). Mirrors ash_e_core.types.Detection field for field.
uint8 STATE_NONE=0
uint8 STATE_HOLDING=1
uint8 STATE_SMOKING=2
uint8 DIST_SRC_NONE=0
uint8 DIST_SRC_PROXY=1
uint8 DIST_SRC_DEPTH=2

uint32  track_id             # tracker id (from 1)
uint8   state                # stabilized state (priority uses only this)
float32 state_confidence     # 0..1, mean raw_confidence of positive observations in the window (0 if none)
uint8   raw_state            # this frame's decision
float32 raw_confidence       # max cigarette box confidence this frame (0 if none)
bool    cigarette_checked    # whether the ROI cigarette check ran this frame
float32 person_confidence
int32   bbox_x               # person box top-left [px, original resolution]
int32   bbox_y
int32   bbox_w
int32   bbox_h
bool    has_cigarette_box
int32   cig_x                # representative cigarette box [px], 0 if none
int32   cig_y
int32   cig_w
int32   cig_h
geometry_msgs/Point position # [m] in header.frame_id (camera color optical frame): x right, y down, z forward
float32 distance_m           # horizontal distance sqrt(x^2+z^2) [m], -1.0 if none
uint8   distance_source
float32 bearing_rad          # REP-103 (left positive) = -atan2(x, z)
float32 stationary_s         # continuous stationary time [s]
uint32  frames_observed      # accumulated observed frames of this track
