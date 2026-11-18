# ash_e_msgs/SmokerDetectionArray  (spec 3.3). core: DetectionArray (stamp float s + frame_id -> header).
std_msgs/Header header
uint32  frame_seq             # processed frame counter
uint32  image_width
uint32  image_height
float32 inference_ms          # whole pipeline time
SmokerDetection[] detections  # only tracks that passed the publish condition (hits >= 2)
