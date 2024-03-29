#! /usr/bin/env python

import rospy
from geometry_msgs.msg import PoseStamped, PoseArray
from mavros_msgs.msg import State
from mavros_msgs.srv import CommandBool, CommandBoolRequest, SetMode, SetModeRequest
from std_srvs.srv import Empty, EmptyResponse
from scipy.spatial.transform import Rotation as R
import numpy as np

# Global mode variable
MODE = "NONE"
LOCAL_POSE = None
WAYPOINTS = None
WAYPOINTS_RECEIVED = False
VICON = None
VICON_TRANSFORM = None
VICON_RECEIVED = False
CURRENT_WAYPOINT = None

# Get states from MAVLink
CURR_STATE = State()

def state_cb(msg):
    global CURR_STATE
    CURR_STATE = msg

# Callback handlers
def handle_launch():
    global MODE
    MODE = "LAUNCH"
    print('Launch Requested. Your drone should take off.')

def handle_test():
    global MODE
    MODE = "TEST"
    print('Test Requested. Your drone should perform the required tasks. Recording starts now.')

def handle_land():
    global MODE
    MODE = "LAND"
    print('Land Requested. Your drone should land.')

def handle_abort():
    global MODE
    MODE = "ABORT"
    print('Abort Requested. Your drone should land immediately due to safety considerations')

def pose_cb(msg):
    global LOCAL_POSE
    LOCAL_POSE = msg.pose

# Service callbacks
def callback_launch(request):
    handle_launch()
    return EmptyResponse()

def callback_test(request):
    handle_test()
    return EmptyResponse()

def callback_land(request):
    handle_land()
    return EmptyResponse()

def callback_abort(request):
    handle_abort()
    return EmptyResponse()

def callback_waypoints(msg):
    global WAYPOINTS_RECEIVED, WAYPOINTS, CURRENT_WAYPOINT

    if WAYPOINTS_RECEIVED:
        return
    
    print('Waypoints Received')

    WAYPOINTS_RECEIVED = True

    WAYPOINTS = np.empty((0,3))
    WAYPOINTS_VICON = np.empty((0,3))

    # Note that we will have received Vicon transform before this
    for pose in msg.poses:
        pos = np.array([pose.position.x, pose.position.y, pose.position.z])
        pos_local = np.matmul(VICON_TRANSFORM[:3, :3], np.transpose(pos)) + VICON_TRANSFORM[:3, 3]
        WAYPOINTS = np.vstack((WAYPOINTS, np.transpose(pos_local)))
        WAYPOINTS_VICON = np.vstack((WAYPOINTS, pos))

    CURRENT_WAYPOINT = 0

    print("Waypoints in local frame:", WAYPOINTS)
    print("Waypoints in vicon frame:", WAYPOINTS_VICON)

    return

def callback_vicon(msg):
    global VICON_TRANSFORM, VICON, LOCAL_POSE, VICON_RECEIVED

    if VICON_RECEIVED:
        return
    
    # Get distance of current local position from origin
    local_position = np.array([[LOCAL_POSE.pose.x], [LOCAL_POSE.pose.y], [LOCAL_POSE.pose.z]])

    # If local pose is not sufficiently close to the origin, discard
    if np.linalg.norm(local_position) > 0.01:
        print("ERROR: Local position too far away from origin.")
        return 

    # Otherwise, get vicon message and break into position and orientation
    VICON = msg.pose

    # Get vector vicon position
    vicon_position = np.array([[VICON.pose.x], [VICON.pose.y], [VICON.pose.z]])

    # Get vicon rotation matrix
    vicon_rotmat = R.fromquat([VICON.orientation.x, VICON.orientation.y, VICON.orientation.z, VICON.orientation.w]).as_matrix()

    # Propagate vicon transform
    VICON_TRANSFORM = np.zeros((4,4))
    VICON_TRANSFORM[3,3] = 1
    VICON_TRANSFORM[:3, :3] = vicon_rotmat.T # Is this correct?
    VICON_TRANSFORM[:3, 3] = -1*np.matmul(vicon_rotmat.T, vicon_position)

    VICON_RECEIVED = True

    print("Vicon transform obtained.")
    print(VICON_TRANSFORM)

    return

if __name__ == "__main__":

    global LOCAL_POSE
    global MODE
    global CURR_STATE
    global WAYPOINTS, WAYPOINTS_RECEIVED
    global VICON, VICON_TRANSFORM, VICON_RECEIVED

    node_name = "rob498_drone_12"

    rospy.init_node(node_name)

    # Basic subs/pubs
    state_sub = rospy.Subscriber("mavros/state", State, callback = state_cb)

    local_pos_sub = rospy.Subscriber("mavros/local_position/pose", PoseStamped , callback = pose_cb) 

    local_pos_pub = rospy.Publisher("mavros/setpoint_position/local", PoseStamped, queue_size=10)

    # Challenge 3 Services
    srv_launch = rospy.Service(node_name + '/comm/launch', Empty, callback_launch)

    srv_test = rospy.Service(node_name + '/comm/test', Empty, callback_test)

    srv_land = rospy.Service(node_name + '/comm/land', Empty, callback_land)

    srv_abort = rospy.Service(node_name + '/comm/abort', Empty, callback_abort)

    sub_waypoints = rospy.Subscriber(node_name+'/comm/waypoints', PoseArray, callback_waypoints)

    sub_vicon = rospy.Subscriber(node_name+'/comm/vicon', PoseStamped, callback_vicon) #TODO: Design callback for Vicon
    
    last_req = rospy.Time.now()

    # Main behaviour
    while(not rospy.is_shutdown()):

        # Setpoint publishing MUST be faster than 2Hz
        rate = rospy.Rate(20)

        # Mode is none
        if (MODE == "NONE") and (not rospy.is_shutdown()):
	        print("MODE is NONE.")
                
            while (MODE == "NONE") and (not rospy.is_shutdown()):
                rate.sleep()
            
        # Mode is launch / test
        elif ((MODE == "LAUNCH") or (MODE == "TEST")) and not rospy.is_shutdown():
        
            print("MODE is LAUNCH or TEST.")
        
            pose = PoseStamped()

    	    while not LOCAL_POSE: 
                print("ERROR: current_local_pose not initialized.")
                rate.sleep()

            while not VICON_TRANSFORM:
                # Vicon will be streaming before test; get transform
                print("Waiting for Vicon transform to be initialized.")
                rate.sleep()
            
            pose.pose.position.x = 0
            pose.pose.position.y = 0
            pose.pose.position.z = 1.5

    	    pose.pose.orientation.x = LOCAL_POSE.orientation.x
            pose.pose.orientation.y = LOCAL_POSE.orientation.y
            pose.pose.orientation.z = LOCAL_POSE.orientation.z
            pose.pose.orientation.w = LOCAL_POSE.orientation.w
            
            while ((MODE == "LAUNCH") or (MODE == "TEST")) and not rospy.is_shutdown():

                # If mode is test
                if MODE == "TEST":

                    # If waypoints haven't been received, continue to publish hover
                    if not WAYPOINTS_RECEIVED:

                        print("Waiting for waypoints...")

                        # Send continuous stream of setpoints
                        local_pos_pub.publish(pose)

                        rate.sleep()

                    # Test behaviour
                    else:

                        pose.pose.position.x = WAYPOINTS[CURRENT_WAYPOINT, 0]
                        pose.pose.position.y = WAYPOINTS[CURRENT_WAYPOINT, 1]
                        pose.pose.position.z = WAYPOINTS[CURRENT_WAYPOINT, 2]

                        local_pos_pub.publish(pose)

                        if np.linalg(WAYPOINTS[CURRENT_WAYPOINT, :] - np.array([LOCAL_POSE.position.x, LOCAL_POSE.position.y, LOCAL_POSE.position.z])) < 0.35:
                            
                            CURRENT_WAYPOINT += 1

                        rate.sleep()
                
                # Publish stream of setpoints before test
                else:

                    # Send continuous stream of setpoints
                    local_pos_pub.publish(pose)

                    rate.sleep()

        elif (MODE == "LAND") and (not rospy.is_shutdown()):
	        
            print("MODE is LAND.")
        
            pose = PoseStamped()
        
            pose.pose.position.x = LOCAL_POSE.pose.x
            pose.pose.position.y = LOCAL_POSE.pose.y
            pose.pose.position.z = LOCAL_POSE.pose.z

    	    pose.pose.orientation.x = LOCAL_POSE.orientation.x
            pose.pose.orientation.y = LOCAL_POSE.orientation.y
            pose.pose.orientation.z = LOCAL_POSE.orientation.z
            pose.pose.orientation.w = LOCAL_POSE.orientation.w
            
            # Continue publishing this setpoint 
            while (MODE == "LAND") and (not rospy.is_shutdown()):
            
                pose.pose.position.z = max(pose.pose.position.z / 1.5, 0.2)

                # Send continuous stream of setpoints
                local_pos_pub.publish(pose)

                rate.sleep()

        elif (MODE == "ABORT") and (not rospy.is_shutdown()):
            print("MODE is ABORT.")
            # For redundancy, send a setpoint to 0
            pose = PoseStamped()
        
            pose.pose.position.x = LOCAL_POSE.position.x
            pose.pose.position.y = LOCAL_POSE.position.y
            pose.pose.position.z = 0

    	    pose.pose.orientation.x = LOCAL_POSE.orientation.x
            pose.pose.orientation.y = LOCAL_POSE.orientation.y
            pose.pose.orientation.z = LOCAL_POSE.orientation.z
            pose.pose.orientation.w = LOCAL_POSE.orientation.w
                     
            # Send a disarm command
            arm_cmd = CommandBoolRequest()
            arm_cmd.value = False

            while(not rospy.is_shutdown() and MODE == "ABORT"):
                
                local_pos_pub.publish(pose)
                
                if(CURR_STATE.armed and (rospy.Time.now() - last_req) > rospy.Duration(5.0)):
                    if(arming_client.call(arm_cmd).success == True):
                        rospy.loginfo("Vehicle disarmed")
            
                last_req = rospy.Time.now()

        else:
            rospy.loginfo("Error: Unrecognised MODE.")