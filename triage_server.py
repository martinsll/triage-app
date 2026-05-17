from unittest import result

from sqlalchemy import engine

from parlam_interfaces.action import Input, Output, Conversation
from rclpy.qos import qos_profile_sensor_data
from std_msgs import msg
from std_srvs.srv import Empty
from std_msgs.msg import String, Bool, Int32
from rcl_interfaces.msg import Parameter
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.action import ActionServer
from rclpy.action import CancelResponse
from rclpy.action import GoalResponse
import threading
from string import Template
import random

import json
import time
import asyncio
from collections import deque

from sensor_msgs.msg import Image
from cv_bridge import CvBridge

import cv2
import cv2.aruco as aruco
import numpy as np
from collections import deque, Counter
import threading
import time

from parlam_pkg.game_engine import GameEngine, Phase

# ─── CONFIG ───────────────────────────────────────────────────────────────────
ARUCO_DICT  = cv2.aruco.DICT_4X4_100
N_SLOTS     = 5
UPSCALE     = 2.0

CORNER_IDS  = {0, 1, 2, 3}
PATIENT_IDS = set(range(10, 50))
DEST_IDS = {50, 51, 52, 53}

DEST_NAMES_SHORT = {
    50: "SurgBay",
    51: "RiskWard",
    52: "MonWard",
    53: "GenWard",
}

ARUCO_TO_DEST = {
    50: "Surgical Bay",
    51: "Risk Ward",
    52: "Monitored Ward",
    53: "General Ward",
}

PATIENT_DB = {
    10:("A","P01"), 11:("A","P02"), 12:("A","P03"), 13:("A","P04"),
    14:("A","P05"), 15:("A","P06"), 16:("A","P07"), 17:("A","P08"),
    18:("A","P09"), 19:("A","P10"), 20:("A","P11"), 21:("A","P12"),
    22:("A","P13"), 23:("A","P14"), 24:("A","P15"), 25:("A","P16"),
    26:("A","P17"), 27:("A","P18"), 28:("A","P19"), 29:("A","P20"),
    30:("B","P01"), 31:("B","P02"), 32:("B","P03"), 33:("B","P04"),
    34:("B","P05"), 35:("B","P06"), 36:("B","P07"), 37:("B","P08"),
    38:("B","P09"), 39:("B","P10"), 40:("B","P11"), 41:("B","P12"),
    42:("B","P13"), 43:("B","P14"), 44:("B","P15"), 45:("B","P16"),
    46:("B","P17"), 47:("B","P18"), 48:("B","P19"), 49:("B","P20"),
}

# class SlotDetector:
#     """
#     Detects which patient card (ArUco ID) is in each of the 5 board slots.
#     Uses the 4 corner markers to define the board boundaries, then assigns
#     patient cards to slots by position.
#     Uses majority vote over MAJORITY_WINDOW frames to avoid flicker.
#     """

#     def __init__(self):
#         self._history = {s: deque(maxlen=MAJORITY_WINDOW) for s in range(1, 6)}

#     def update(self, corners, ids):
#         """
#         corners: output of aruco.detectMarkers
#         ids:     flat list of detected marker IDs
#         Returns: dict {slot_num (1-5): aruco_id} for confirmed cards
#         """
#         if ids is None or len(ids) == 0:
#             for s in range(1, 6):
#                 self._history[s].append(None)
#             return {}

#         id_to_center = {}
#         for i, marker_id in enumerate(ids):
#             c = corners[i][0]
#             cx = float(np.mean(c[:, 0]))
#             cy = float(np.mean(c[:, 1]))
#             id_to_center[int(marker_id)] = (cx, cy)

#         patient_markers = {k: v for k, v in id_to_center.items()
#                            if k not in CORNER_IDS}
#         slots = {}
#         if patient_markers:
#             all_x = [v[0] for v in patient_markers.values()]
#             min_x, max_x = min(all_x), max(all_x)
#             width = max(max_x - min_x, 1)
#             for marker_id, (cx, cy) in patient_markers.items():
#                 col  = min(4, int(((cx - min_x) / width) * 5))
#                 slot = col + 1
#                 slots[slot] = marker_id

#         for slot in range(1, 6):
#             self._history[slot].append(slots.get(slot))

#         confirmed = {}
#         for slot in range(1, 6):
#             hist = [v for v in self._history[slot] if v is not None]
#             if len(hist) >= MAJORITY_WINDOW // 2:
#                 confirmed[slot] = Counter(hist).most_common(1)[0][0]

#         return confirmed


class TriageServer(Node):
    """
    Triage Game — ROS 2 Node
    =========================
    Two learning modes:
    guided_learning  — robot guides one slot at a time, auto-advances on correct
    error_based      — participant places all 5, says "validate", robot corrects
    """
    def __init__(self):
        super().__init__('triage_server',
                         allow_undeclared_parameters=True, 
                         automatically_declare_parameters_from_overrides=True)  

        self._action_cb_group = ReentrantCallbackGroup() # MutuallyExclusiveCallbackGroup()
        self._topic_cb_group = ReentrantCallbackGroup()
        self._service_cb_group = ReentrantCallbackGroup()

        self.input_cancel_pending=False
        self.output_cancel_pending=False

        self._timer = self.create_timer(0.1, self.timer_callback, callback_group=self._action_cb_group)

        self.get_logger().info("\n --------- \n PARAMETERS \n ---------")
        # Declare parameters
        if not self.has_parameter("debug"):
            self.get_logger().info("Declaring default value for debug parameter...")
            self.declare_parameter("debug", False)
        if not self.has_parameter("documents_path"):
            self.get_logger().info("Declaring default value for data...")
            self.declare_parameter("documents_path", "")

        # Set parameters
        self.get_logger().info("Interaction language: " + self.get_parameter("language").value) #en, es
        self.get_logger().info("Conversation file directory: " + self.get_parameter("directory").value) 
        self.get_logger().info("Bool save conversation: " + str(self.get_parameter("save_conversation").value)) 
        self.get_logger().info("ID experiment: " + str(self.get_parameter("id_experiment").value)) 
        self.get_logger().info("Documents path: " + self.get_parameter("documents_path").value) 
        self.get_logger().info(f"Instructions: {self.get_parameter('instructions').value}")
        self.get_logger().info(f"Camera topic: {self.get_parameter('camera_topic').value}")
        self.get_logger().info("\n --------- \n LOGS \n ---------")

        cam_topic = self.get_parameter('camera_topic').value
        self.debug = self.get_parameter('debug').value
        # Camera subscriber
        self.bridge        = CvBridge()
        #self.slot_detector = SlotDetector()
        self._last_board   = {}
        self._last_corner_markers = []
        self._cam_lock = threading.Lock()
        self.cam_sub = self.create_subscription(
            Image, cam_topic, self._camera_cb, qos_profile_sensor_data, callback_group=self._topic_cb_group)
        self._dest_last_seen = {}

        # # State flags — prevent overlapping speak/listen calls
        self._speaking  = False
        self._listening = False

        # Client Input
        self.input_client = ActionClient(self, Input, 'input_action')
        self.input_client.wait_for_server()

        # Client Output
        self.output_client = ActionClient(self, Output, 'output_action')
        self.output_client.wait_for_server()

        # Skip service 
        # self.srv_skip = self.create_service(Empty, 
        #                                     'skip_conversation', 
        #                                     self.skip_callback, 
        #                                     callback_group=self._service_cb_group)
        # self.skip_lock = threading.Lock()

        # # Output topic publisher
        # self.text_publisher = self.create_publisher(
        #     String,
        #     '/output_text',
        #     1
        # )

        self.aruco_dict   = cv2.aruco.getPredefinedDictionary(ARUCO_DICT)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.aruco_det    = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

        #### CHANGES #####
        # Improve corner precision
        self.aruco_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX

        # Better small-marker detection
        self.aruco_params.adaptiveThreshWinSizeMin = 3
        self.aruco_params.adaptiveThreshWinSizeMax = 23
        self.aruco_params.adaptiveThreshWinSizeStep = 10

        # Allow smaller markers
        self.aruco_params.minMarkerPerimeterRate = 0.02

        # Reduce false rejection
        self.aruco_params.polygonalApproxAccuracyRate = 0.03

        # Allow closer markers
        self.aruco_params.minCornerDistanceRate = 0.02

        # Helps near image borders
        self.aruco_params.minDistanceToBorder = 2

        self.aruco_det = cv2.aruco.ArucoDetector(
            self.aruco_dict,
            self.aruco_params
        )

        ##################

        # Action server for Behavior Tree
        self._action_server = ActionServer(
            self,
            Conversation,
            'conversation_action',
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self._action_cb_group
        )

        # Store active child goal handles
        self.current_input_goal = None
        self.current_output_goal = None

        # Import instructions
        # with open(self.get_parameter("documents_path").value+"/instructions.txt", "r", encoding="utf-8") as f:
        #     self.instructions_text = f.read()
        
        # Load patients data
        # with open(self.get_parameter("documents_path").value+"/patients.json", "r", encoding="utf-8") as f:
        #     self.patients_data = json.load(f)

        self.get_logger().info("Triage server is ready.")

    def timer_callback(self):
        if self.input_cancel_pending and self.current_input_goal is not None:
            self.get_logger().info("Cancelling input goal from timer callback")
            self.current_input_goal.cancel_goal_async()
            self.input_cancel_pending=False

        if self.output_cancel_pending and self.current_output_goal is not None:
            self.get_logger().info("Cancelling Output goal from timer callback")
            self.current_output_goal.cancel_goal_async()
            self.output_cancel_pending=False

    async def execute_callback(self, goal_handle):
        params = goal_handle.request.goal
        interaction_data = [] 
        #self.active_goal_handle = goal_handle
        result = Conversation.Result()
        if not params:
            self.get_logger().info("Received empty goal, missing robot mode parameter, aborting...")
            goal_handle.abort()
            return Conversation.Result()
        else:
            for p in params:
                if p.name == "mode":
                    mode = p.value.string_value
                    self.get_logger().info(f"Received goal with mode: {mode}")
                elif p.name == "iteration": #All patients from set A, but choose group 1,2,3
                    iteration = p.value.integer_value
                    self.get_logger().info(f"Received goal with iteration: {iteration}")
                
        if mode is None :
            self.get_logger().info("No mode provided")
            goal_handle.abort()
            return Conversation.Result()
        if iteration is None:
            self.get_logger().info("No iteration provided")
            goal_handle.abort()
            return Conversation.Result()

        if mode == "test":

            while rclpy.ok():
                if goal_handle.is_cancel_requested:
                        if self.debug:
                            self.get_logger().info('Received cancel goal handle conversation server...')
                        self.cancel_all_children()
                        goal_handle.canceled()
                        self.input_cancel_pending=False
                        self.output_cancel_pending=False
                        self._active_goal_handle = None
                        self.get_logger().info('Ending goal as canceled...')
                        # end_time = time.time()
                        # total_duration = round(end_time - start_time, 2)
                        # if self.get_parameter("save_conversation").value:
                        #     file_name = f'{self.get_parameter("id_experiment").value}_'
                        #     self.get_logger().info('Saving new conversation file: ' + (file_name))
                        #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
                        #                                 total_duration=total_duration, 
                        #                                 total_true_looks=self.look_counter_true, 
                        #                                 total_false_looks=self.look_counter_false, 
                        #                                 change_of_position=self.position_counter, 
                        #                                 total_skips=self.skipped_counter, 
                        #                                 conversation_data=interaction_data)
                        return result
                try:
                    board_state, all_visible, dest_state, all_visible_dest, dest_state_integer, board_found, corner_markers = self._get_board()
                    self.get_logger().info(f"Current board state: {board_state} | All visible: {all_visible} | Destination state: {dest_state} | All visible destinations: {all_visible_dest} | Board found: {board_found}")
            
                except Exception as e:
                    self.get_logger().error(f"Error occurred while fetching board state: {e}")
                    if self.debug:
                        self.get_logger().info('Received cancel goal handle conversation server...')
                    self.cancel_all_children()
                    goal_handle.canceled()
                    self.input_cancel_pending=False
                    self.output_cancel_pending=False
                    self._active_goal_handle = None
                    self.get_logger().info('Ending goal as canceled...')
                    return result
                time.sleep(1)
  
        else:
            self.engine = GameEngine(
                set_label="A",
                mode=mode,
                language=self.get_parameter("language").value,
            )
            self._iteration_done = False
            ################### START ITERATION #################
            actions = self.engine.start_iteration(iteration)

            for action in actions:
                atype = action['type']
                if atype == 'speak':
                    self._speaking = True
                    try:
                        self.publish_feedback(goal_handle=goal_handle, state_string="Speaking")
                        if self.debug:
                            self.get_logger().info('Send goal to output server...')
                        
                        success = await self.handle_output(goal_handle,
                                                        text= action['text'], 
                                                        use_text_field = True)
                        if not success:
                            if self.debug:
                                self.get_logger().info('Output goal not success...')
                            self.cancel_all_children()
                            goal_handle.canceled()
                            self._active_goal_handle = None
                            self.input_cancel_pending=False
                            self.output_cancel_pending=False
                            self.get_logger().info('Ending goal as canceled...')
                            return result
                        self.publish_feedback(goal_handle=goal_handle, output_text=action['text'])
                        interaction_data.append(["", action['text']])
                    finally:
                        self._speaking = False

                elif atype == 'listen':

                    self._listening = True

                    try:
                        self.publish_feedback(goal_handle=goal_handle, state_string="Listening")
                        if self.debug:
                            self.get_logger().info('Send goal to input server...')

                        success, input = await self.handle_input(goal_handle)
                        if not success:
                            if self.debug:
                                self.get_logger().info('Input goal not success...')
                            self.cancel_all_children()
                            goal_handle.canceled()
                            self._active_goal_handle = None
                            self.input_cancel_pending=False
                            self.output_cancel_pending=False
                            self.get_logger().info('Ending goal as canceled...')
                            return result
                    finally:
                        self._listening = False
                        self.engine.trigger_evaluation()

                elif atype == 'log':
                    self.get_logger().info(
                        f"[LOG] {action.get('phase')} "
                        f"attempt {action.get('attempt','?')}: "
                        f"{action.get('score','?')}")
                elif atype == 'state_change':
                    self.get_logger().info(f"[STATE] → {action.get('phase')}")
                    # if action.get('phase') in ("PLACEMENT", "PROCESS_PLACING"):
                    #     self._listening = True
                    #     input = "offconv"
                    #     try:
                    #         while input == "offconv":
                    #             self.publish_feedback(goal_handle=goal_handle, state_string="Listening to validate")
                    #             if self.debug:
                    #                 self.get_logger().info('Send goal to input server...')

                    #             success, input = await self.handle_input(goal_handle)
                    #             if not success:
                    #                 if self.debug:
                    #                     self.get_logger().info('Input goal not success...')
                    #                 self.cancel_all_children()
                    #                 goal_handle.canceled()
                    #                 self._active_goal_handle = None
                    #                 self.input_cancel_pending=False
                    #                 self.output_cancel_pending=False
                    #                 self.get_logger().info('Ending goal as canceled...')
                    #                 return result
                    #     finally:
                    #         self._listening = False
                    #     self.get_logger().info("Trigger evaluation...")
                    #     self.engine.trigger_evaluation()
            
                elif atype == 'end_iteration':
                    self.get_logger().info(
                        f"[GAME] Iteration complete: {action.get('summary',{})}")
                    self._iteration_done = True

            ################### CONTINUE ITERATION ######################
            while not self._iteration_done:

                if goal_handle.is_cancel_requested:
                    if self.debug:
                        self.get_logger().info('Received cancel goal handle conversation server...')
                    self.cancel_all_children()
                    goal_handle.canceled()
                    self.input_cancel_pending=False
                    self.output_cancel_pending=False
                    self._active_goal_handle = None
                    self.get_logger().info('Ending goal as canceled...')
                    # end_time = time.time()
                    # total_duration = round(end_time - start_time, 2)
                    # if self.get_parameter("save_conversation").value:
                    #     file_name = f'{self.get_parameter("id_experiment").value}_'
                    #     self.get_logger().info('Saving new conversation file: ' + (file_name))
                    #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
                    #                                 total_duration=total_duration, 
                    #                                 total_true_looks=self.look_counter_true, 
                    #                                 total_false_looks=self.look_counter_false, 
                    #                                 change_of_position=self.position_counter, 
                    #                                 total_skips=self.skipped_counter, 
                    #                                 conversation_data=interaction_data)
                    return result

                if self.engine.phase != Phase.IDLE:
                
                    try:
                        board_state, all_visible, dest_state, all_visible_dest_ids, dest_state_integer, board_found, corner_markers = self._get_board()
                        self.get_logger().info(f"Current board state: {board_state} | All visible: {all_visible} | Destination state: {dest_state} | All visible destinations: {all_visible_dest_ids} | Board found: {board_found}")
                        status = self.format_status(self.engine, board_state, dest_state_integer, len(corner_markers), board_found)
                    except Exception as e:
                        self.get_logger().error(f"Error occurred while fetching board state: {e}")
                        if self.debug:
                            self.get_logger().info('Received cancel goal handle conversation server...')
                        self.cancel_all_children()
                        goal_handle.canceled()
                        self.input_cancel_pending=False
                        self.output_cancel_pending=False
                        self._active_goal_handle = None
                        self.get_logger().info('Ending goal as canceled...')
                        # end_time = time.time()
                        # total_duration = round(end_time - start_time, 2)
                        # if self.get_parameter("save_conversation").value:
                        #     file_name = f'{self.get_parameter("id_experiment").value}_'
                        #     self.get_logger().info('Saving new conversation file: ' + (file_name))
                        #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
                        #                                 total_duration=total_duration, 
                        #                                 total_true_looks=self.look_counter_true, 
                        #                                 total_false_looks=self.look_counter_false, 
                        #                                 change_of_position=self.position_counter, 
                        #                                 total_skips=self.skipped_counter, 
                        #                                 conversation_data=interaction_data)
                        return result
                    actions = self.engine.update(
                        board_state,
                        all_visible,
                        dest_state
                    )

                if actions:
                    for action in actions:
                        atype = action['type']
                        if atype == 'speak':
                            self._speaking = True
                            try:
                                self.publish_feedback(goal_handle=goal_handle, state_string="Speaking")
                                if self.debug:
                                    self.get_logger().info('Send goal to output server...')
                                
                                success = await self.handle_output(goal_handle,
                                                                text= action['text'], 
                                                                use_text_field = True)
                                if not success:
                                    if self.debug:
                                        self.get_logger().info('Output goal not success...')
                                    self.cancel_all_children()
                                    goal_handle.canceled()
                                    self._active_goal_handle = None
                                    self.input_cancel_pending=False
                                    self.output_cancel_pending=False
                                    self.get_logger().info('Ending goal as canceled...')
                                    return result
                                self.publish_feedback(goal_handle=goal_handle, output_text=action['text'])
                                interaction_data.append(["", action['text']])
                            finally:
                                self._speaking = False

                        elif atype == 'listen':

                            self._listening = True
                            input = "offconv"
                            try:
                                while input == "offconv":
                                    self.publish_feedback(goal_handle=goal_handle, state_string="Listening")
                                    if self.debug:
                                        self.get_logger().info('Send goal to input server...')

                                    success, input = await self.handle_input(goal_handle)
                                    if not success:
                                        if self.debug:
                                            self.get_logger().info('Input goal not success...')
                                        self.cancel_all_children()
                                        goal_handle.canceled()
                                        self._active_goal_handle = None
                                        self.input_cancel_pending=False
                                        self.output_cancel_pending=False
                                        self.get_logger().info('Ending goal as canceled...')
                                        return result
                                    board_state, all_visible, dest_state, all_visible_dest_ids, dest_state_integer, board_found, corner_markers = self._get_board()
                                    self.get_logger().info(f"Current board state: {board_state} | All visible: {all_visible} | Process state: {dest_state} | All visible destinations: {all_visible_dest_ids} | Board found: {board_found}")
                            finally:
                                self._listening = False
                                self.engine.trigger_evaluation()

                        elif atype == 'log':
                            self.get_logger().info(
                                f"[LOG] {action.get('phase')} "
                                f"attempt {action.get('attempt','?')}: "
                                f"{action.get('score','?')}")
                        elif atype == 'state_change':
                            self.get_logger().info("Received state change")
                            self.get_logger().info(f"[STATE] → {action.get('phase')}")
                            # if action.get('phase') in ("PLACEMENT", "PROCESS_PLACING"):
                            #     self._listening = True
                            #     input = "offconv"
                            #     try:
                            #         while input == "offconv":
                            #             self.publish_feedback(goal_handle=goal_handle, state_string="Listening to validate")
                            #             if self.debug:
                            #                 self.get_logger().info('Send goal to input server...')

                            #             success, input = await self.handle_input(goal_handle)
                            #             if not success:
                            #                 if self.debug:
                            #                     self.get_logger().info('Input goal not success...')
                            #                 self.cancel_all_children()
                            #                 goal_handle.canceled()
                            #                 self._active_goal_handle = None
                            #                 self.input_cancel_pending=False
                            #                 self.output_cancel_pending=False
                            #                 self.get_logger().info('Ending goal as canceled...')
                            #                 return result
                            #     finally:
                            #         self._listening = False
                            #     self.get_logger().info("Trigger evaluation...")
                            #     self.engine.trigger_evaluation()

                        elif atype == 'end_iteration':
                            self.get_logger().info(
                                f"[GAME] Iteration complete: {action.get('summary',{})}")
                            self._iteration_done = True
                #await asyncio.sleep(0.1)
                time.sleep(0.5)

            result = Conversation.Result()
            goal_handle.succeed()
            return result

    def publish_feedback(
                self,
                goal_handle,
                state_string: str = None,
                input_text: str = None,
                output_text: str = None,
                move_value: bool = None
            ):
                
        feedback_msg = Conversation.Feedback()
        feedback_msg.feedback = []

        if state_string is not None:
            state_msg = Parameter()
            state_msg.name = "feedback_state"
            state_msg.value.type = 4
            state_msg.value.string_value = state_string
            feedback_msg.feedback.append(state_msg)

        if input_text is not None:
            input_dialog = Parameter()
            input_dialog.name = "input_dialog"
            input_dialog.value.type = 4
            input_dialog.value.string_value = input_text
            feedback_msg.feedback.append(input_dialog)

        if output_text is not None:
            output_dialog = Parameter()
            output_dialog.name = "output_dialog"
            output_dialog.value.type = 4
            output_dialog.value.string_value = output_text
            feedback_msg.feedback.append(output_dialog)
        
        # Only publish if something was actually added
        if feedback_msg.feedback:
            goal_handle.publish_feedback(feedback_msg)

    async def handle_input(self, goal_handle, listen_time=0):

        if goal_handle.is_cancel_requested:
            return False, ""

        input_goal = Input.Goal(listen_time=listen_time)

        self.current_input_goal = await self.input_client.send_goal_async(input_goal)

        if not self.current_input_goal.accepted:
            return False, ""

        result_future = await self.current_input_goal.get_result_async()
        self.current_input_goal = None

        if goal_handle.is_cancel_requested:
            return False, ""
        
        return True, result_future.result.user_input
    
    async def handle_output(self, goal_handle, text, use_text_field):
        """
        Trigger Output goal.
        """
        if goal_handle.is_cancel_requested:
            return False, ""
        
        # Output
        output_goal = Output.Goal(text=text, use_text_field=use_text_field)
        self.current_output_goal = await self.output_client.send_goal_async(
            output_goal
        )

        if not self.current_output_goal.accepted:
            self.current_output_goal = None
            return False, ""
        
        await self.current_output_goal.get_result_async()
        self.current_output_goal = None

        if goal_handle.is_cancel_requested:
            return False, ""
        
        return True

    def preprocess(self,frame, upscale=UPSCALE):
        h, w = frame.shape[:2]
        large = cv2.resize(frame, (int(w*upscale), int(h*upscale)),
                        interpolation=cv2.INTER_CUBIC)
        gray  = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        gray  = clahe.apply(gray)
        _, binary = cv2.threshold(gray, 0, 255,
                                cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    # ─── ARUCO DETECTION ──────────────────────────────────────────────────────────
    def detect_all_markers(self, frame, detector):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = detector.detectMarkers(gray)
        result = {}
        if ids is not None:
            for i, mid in enumerate(ids.flatten()):
                #result[int(mid)] = corners[i][0]
                mid = int(mid)
                result.setdefault(mid, []).append(corners[i][0])
        return result

    # ─── BOARD GEOMETRY ───────────────────────────────────────────────────────────
    def get_board_corners(self,markers):
        if not {0,1,2,3}.issubset(markers.keys()):
            return None
        # Use centroid of each corner marker — stable regardless of orientation
        return np.array([
            markers[0][0].mean(axis=0),  # centre of TL marker. S'afegeix [0] a les 4 linies.
            markers[1][0].mean(axis=0),  # centre of TR marker
            markers[2][0].mean(axis=0),  # centre of BL marker
            markers[3][0].mean(axis=0),  # centre of BR marker
        ], dtype=np.float32)

    def compute_slots(self, board_corners, n=N_SLOTS):
        tl, tr, bl, br = board_corners
        slots = []
        for i in range(n):
            t0 = tl + (tr-tl) * (i/n)
            t1 = tl + (tr-tl) * ((i+1)/n)
            b0 = bl + (br-bl) * (i/n)
            b1 = bl + (br-bl) * ((i+1)/n)
            slots.append(np.array([t0,t1,b1,b0], dtype=np.float32))
        return slots

    def find_slot(self, centre, slots):
        """Returns slot index (0-based) or None. Uses actual pixel distance."""
        for idx, poly in enumerate(slots):
            dist = cv2.pointPolygonTest(poly,
                                        (float(centre[0]), float(centre[1])),
                                        True)   # True = actual distance
            if dist >= -5:
                return idx
        return None

    def find_slot_majority(self, corners_array, slots):
        """
        Assign a marker to a slot by majority vote across all 4 corners.
        More robust than centroid-only when marker straddles a slot boundary.
        Falls back to centroid if no corners land in any slot.
        """
        votes = {}
        for corner in corners_array:
            idx = self.find_slot(corner, slots)
            if idx is not None:
                votes[idx] = votes.get(idx, 0) + 1

        if not votes:
            return self.find_slot(corners_array.mean(axis=0), slots)

        return max(votes, key=lambda k: (votes[k], -k))

    # ─── SCENE PARSER ─────────────────────────────────────────────────────────────
    def parse_scene(self, markers, board_corners):
        """
        Returns:
        board_state:     {slot(1-5): pid}
        all_visible_ids: [aruco_id, ...]  all patient IDs visible anywhere
        dest_state:      {pid: dest_aruco_id}  — one destination card per patient
        """
        if board_corners is None:
            return {}, [], {}

        slots = self.compute_slots(board_corners)
        slot_to_patient   = {}   # slot_idx → pid
        slot_to_dest      = {}   # slot_idx → aruco_id (one per slot)

        '''
        for aruco_id, corners in markers.items():
            # Use majority corner voting for robust slot assignment
            slot_idx = self.find_slot_majority(corners, slots)
            if slot_idx is None:
                continue
            if aruco_id in PATIENT_IDS:
                _, pid = PATIENT_DB[aruco_id]
                slot_to_patient[slot_idx] = pid
            elif aruco_id in DEST_IDS:
                slot_to_dest[slot_idx] = aruco_id
        '''
        for aruco_id, detections in markers.items():
            for corners in detections:
                slot_idx = find_slot_majority(corners, slots)
                if slot_idx is None:
                    continue
                if aruco_id in PATIENT_IDS:
                    _, pid = PATIENT_DB[aruco_id]
                    slot_to_patient[slot_idx] = pid
                elif aruco_id in DEST_IDS:
                    slot_to_dest[slot_idx] = aruco_id

        board_state = {idx+1: pid for idx, pid in slot_to_patient.items()}
        dest_state  = {}
        for slot_idx, dest_id in slot_to_dest.items():
            pid = slot_to_patient.get(slot_idx)
            if pid:
                dest_state[pid] = [dest_id]  # list for compatibility with stability buffer

        all_visible = [aid for aid in markers if aid in PATIENT_IDS]
        all_visible_dest_ids = [aid for aid in markers if aid in DEST_IDS]
        return board_state, all_visible, dest_state, all_visible_dest_ids

    def format_status(self, engine, board_state, dest_state_int,
                    corners_found, board_found):
        phase = engine.phase.name
        if not board_found:
            return f"[{corners_found}/4 corners] [Phase: {phase}]"
        parts = []
        for slot in range(1, N_SLOTS+1):
            pid      = board_state.get(slot, "----")
            dest_ids = dest_state_int.get(pid, []) if pid != "----" else []
            dest_str = DEST_NAMES_SHORT.get(dest_ids[0], "?") if dest_ids else ""
            cell = f"[{slot}:{pid}" + (f"|{dest_str}" if dest_str else "") + "]"
            parts.append(cell)
        return f"[{phase}]  " + "  ".join(parts)

    def _camera_cb(self, msg):
        """
        Receive camera frame, detect ArUco markers,
        parse board state, and cache latest perception.
        """

        import time

        try:
            # ROS Image -> OpenCV image
            frame = self.bridge.imgmsg_to_cv2(
                msg,
                desired_encoding='passthrough'
            )

            # Convert YUY2 -> BGR
            if self.get_parameter('camera_topic').value == "image_raw":
                frame = cv2.cvtColor(
                    frame,
                    cv2.COLOR_YUV2BGR_YUY2
                )
            else: 
                frame = self.bridge.imgmsg_to_cv2(
                    msg,
                    desired_encoding='bgr8'
                )

        except Exception as e:
            self.get_logger().error(f"CvBridge error: {e}")
            return

        try:
            # Detect markers
            markers = self.detect_all_markers(frame,self.aruco_det)

            # Extract board corner markers
            corner_markers = {
                k: v for k, v in markers.items()
                if k in CORNER_IDS}
            
            # Compute board corners
            board_corners = self.get_board_corners(corner_markers)

            board_found = board_corners is not None

            # Parse scene
            board_state, all_visible, raw_dest_state, all_visible_dest_ids = self.parse_scene(
                markers,
                board_corners
            )

            # STABLE PROCESS TRACKING (TIME-BASED)

            now = time.time()

            # Timeout in seconds before removing unseen markers
            VISIBLE_TIMEOUT = 1.0

            # Update last-seen timestamps

            for pid, dest_ids in raw_dest_state.items():
                for dest_id in dest_ids:
                    key = (pid, dest_id)
                    self._dest_last_seen[key] = now

            # Build stable process state

            stable_dests = {}

            expired_keys = []

            for (pid, dest_id), last_seen in self._dest_last_seen.items():

                # Keep marker alive for timeout window
                if (now - last_seen) < VISIBLE_TIMEOUT:
                    stable_dests.setdefault(pid, set()).add(dest_id)

                else:
                    expired_keys.append((pid, dest_id))

            # Cleanup expired markers

            for key in expired_keys:
                del self._dest_last_seen[key]

            # Convert sets -> sorted lists

            dest_state_integer = {
                pid: sorted(procs)
                for pid, procs in stable_dests.items()
            }

            dest_state = {
                pid: sorted(
                    ARUCO_TO_DEST.get(p, p)
                    for p in procs
                )
                for pid, procs in stable_dests.items()
            }

            # ------------------------------------------------------------
            # Debug logging
            # ------------------------------------------------------------

            # self.get_logger().info(
            #     f"RAW: {raw_dest_state} | "
            #     f"STABLE: {dest_state_integer}"
            # )

            # Cache latest perception

            with self._cam_lock:

                self._last_board = board_state
                self._last_all_visible = all_visible
                self._last_dest_state = dest_state
                self._last_all_visible_dest_ids = all_visible_dest_ids
                self._last_dest_state_integer = dest_state_integer
                self._last_board_found = board_found
                self._last_corner_markers = corner_markers

        except Exception as e:

            self.get_logger().error(
                f"Camera callback failed: {e}"
            )


    def _get_board(self):

        with self._cam_lock:
            return (
                dict(self._last_board),
                self._last_all_visible,
                dict(self._last_dest_state),
                self._last_all_visible_dest_ids,
                self._last_dest_state_integer,
                self._last_board_found,
                self._last_corner_markers
            )
        
    def goal_callback(self, goal_request):
        '''
        Accepts or rejects a client request to begin an action.
        '''
        self.get_logger().info('Received goal request')
        return GoalResponse.ACCEPT
    
    def cancel_callback(self, goal_handle):

        self.get_logger().info("Received conversation cancel request")
        self.cancel_all_children()

        return CancelResponse.ACCEPT
    
    def cancel_all_children(self):

        self.input_cancel_pending=True
        self.output_cancel_pending=True

        if self.current_input_goal is not None:
            self.get_logger().info("Cancelling input goal")
            self.current_input_goal.cancel_goal_async()
            self.input_cancel_pending=False

        if self.current_output_goal is not None:
            self.get_logger().info("Cancelling TTS goal")
            self.current_output_goal.cancel_goal_async()
            self.output_cancel_pending=False

def main(args=None):
    rclpy.init(args=args)

    conversation = TriageServer()
    executor = MultiThreadedExecutor(4)
    executor.add_node(conversation)
    executor.spin()

    conversation.get_logger().info('Destroying node...')
    conversation.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()



# class TriageServer(Node):

#     def __init__(self):
#         super().__init__('triage_server',
#                          allow_undeclared_parameters=True, 
#                          automatically_declare_parameters_from_overrides=True)  

#         self._action_cb_group = ReentrantCallbackGroup() # MutuallyExclusiveCallbackGroup()
#         self._topic_cb_group = ReentrantCallbackGroup()
#         self._service_cb_group = ReentrantCallbackGroup()

#         self.input_cancel_pending=False
#         self.output_cancel_pending=False

#         self._timer = self.create_timer(0.1, self.timer_callback, callback_group=self._action_cb_group)

#         self.get_logger().info("\n --------- \n PARAMETERS \n ---------")
#         # Declare parameters
#         if not self.has_parameter("debug"):
#             self.get_logger().info("Declaring default value for debug parameter...")
#             self.declare_parameter("debug", False)
#         if not self.has_parameter("documents_path"):
#             self.get_logger().info("Declaring default value for data...")
#             self.declare_parameter("documents_path", "")

#         # Set parameters
#         self.get_logger().info("Interaction language: " + self.get_parameter("language").value) #en, es
#         self.get_logger().info("Conversation file directory: " + self.get_parameter("directory").value) 
#         self.get_logger().info("Bool save conversation: " + str(self.get_parameter("save_conversation").value)) 
#         self.get_logger().info("ID experiment: " + str(self.get_parameter("id_experiment").value)) 
#         self.get_logger().info("Documents path: " + self.get_parameter("documents_path").value) 
#         self.get_logger().info(f"Instructions: {self.get_parameter('instructions').value}")

#         self.get_logger().info("\n --------- \n LOGS \n ---------")

#         # Client Input
#         self.input_client = ActionClient(self, Input, 'input_action')
#         self.input_client.wait_for_server()

#         # Client Output
#         self.output_client = ActionClient(self, Output, 'output_action')
#         self.output_client.wait_for_server()

#         # Client Visual
#         #TODO: IMPLEMENT CALL TO VISION ACTION SERVER AND WAIT FOR IT, SIMILAR TO LISTEN
#         self.visual_client = ActionClient(self, Visual, 'visual_action')
#         self.visual_client.wait_for_server()

#         # Skip service 
#         # self.srv_skip = self.create_service(Empty, 
#         #                                     'skip_conversation', 
#         #                                     self.skip_callback, 
#         #                                     callback_group=self._service_cb_group)
#         # self.skip_lock = threading.Lock()

#         # # Output topic publisher
#         # self.text_publisher = self.create_publisher(
#         #     String,
#         #     '/output_text',
#         #     1
#         # )

#         # Action server for Behavior Tree
#         self._action_server = ActionServer(
#             self,
#             Conversation,
#             'conversation_action',
#             execute_callback=self.execute_callback,
#             goal_callback=self.goal_callback,
#             cancel_callback=self.cancel_callback,
#             callback_group=self._action_cb_group
#         )

#         # Store active child goal handles
#         self.current_input_goal = None
#         self.current_output_goal = None

#         # Import instructions
#         # with open(self.get_parameter("documents_path").value+"/instructions.txt", "r", encoding="utf-8") as f:
#         #     self.instructions_text = f.read()
        
#         # Load patients data
#         with open(self.get_parameter("documents_path").value+"/patients.json", "r", encoding="utf-8") as f:
#             self.patients_data = json.load(f)

#         self.get_logger().info("Triage server is ready.")

#     def timer_callback(self):
#         if self.input_cancel_pending and self.current_input_goal is not None:
#             self.get_logger().info("Cancelling input goal from timer callback")
#             self.current_input_goal.cancel_goal_async()
#             self.input_cancel_pending=False

#         if self.output_cancel_pending and self.current_output_goal is not None:
#             self.get_logger().info("Cancelling Output goal from timer callback")
#             self.current_output_goal.cancel_goal_async()
#             self.output_cancel_pending=False

#     async def execute_callback(self, goal_handle):
#         self._active_goal_handle = goal_handle
#         params = goal_handle.request.goal
#         result = Conversation.Result()
#         # self.is_skipped = False
#         mode = None
#         patients_group = None
#         validated = False
#         interaction_data = [] 

#         # Check if empty goal
#         if not params:
#             self.get_logger().info("Received empty goal, missing robot mode parameter, aborting...")
#             goal_handle.abort()
#             return Conversation.Result()
#         else:
#             for p in params:
#                 if p.name == "mode":
#                     mode = p.value.string_value
#                     self.get_logger().info(f"Received goal with mode: {mode}")
#                 elif p.name == "patients_group": #All patients from set A, but choose group 1,2,3
#                     patients_group = p.value.integer_value
#                     self.get_logger().info(f"Received goal with patients group: {patients_group}")
                
#         if mode is None :
#             self.get_logger().info("No mode provided")
#             goal_handle.abort()
#             return Conversation.Result()
#         if patients_group is None:
#             self.get_logger().info("No patients group provided")
#             goal_handle.abort()
#             return Conversation.Result()

#         # start_time = time.time()

#         instruction_keys = [
#             f"exp_selection_{self.get_parameter('language').value}",
#             f"exp_processes_{self.get_parameter('language').value}",
#             f"exp_destination_{self.get_parameter('language').value}"
#         ]

#         control_steps =  []

#         patients = [
#             patient
#             for patient in self.patients_data.get("set_a", [])
#             if patient.get("group") == patients_group
#         ]

#         for key in instruction_keys:
#             for patient in patients:

#                 value = patient.get(key)

#                 if value:
#                     control_steps.append((patient.get("pid"),value))

#         self.get_logger().info(f"Loaded control steps for group {patients_group}: {control_steps}")

#         # TODO: integrate head motion with speaking or listening 

#         if mode == "guide":
#             # Start with instructions if it is the first interaction

#             if self.get_parameter("instructions").value: #Start with instructions
#                 self.publish_feedback(goal_handle=goal_handle, state_string="Speaking")
#                 await self.send_instructions(goal_handle, self.instructions_text)

#             # Say start sentence
#             self.publish_feedback(goal_handle=goal_handle, state_string="Speaking")
#             if self.debug:
#                 self.get_logger().info('Send goal to output server...')
#             text_to_speak = "I will now give you the first instruction to do the task."
#             success = await self.handle_output(goal_handle,
#                                             text= text_to_speak,  
#                                             use_text_field = True)
#             if not success:
#                 if self.debug:
#                     self.get_logger().info('Output goal not success...')
#                 self.cancel_all_children()
#                 goal_handle.canceled()
#                 self._active_goal_handle = None
#                 self.input_cancel_pending=False
#                 self.output_cancel_pending=False
#                 self.get_logger().info('Ending goal as canceled...')
#                 # end_time = time.time()
#                 # total_duration = round(end_time - start_time, 2)
#                 # if self.get_parameter("save_conversation").value:
#                 #     file_name = f'{self.get_parameter("id_experiment").value}_{self.interaction_order}_S{self.get_parameter("system").value}_P{self.get_parameter("patient").value}'
#                 #     self.get_logger().info('Saving new conversation file: ' + (file_name))
#                 #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
#                 #                              total_duration=total_duration, 
#                 #                              total_true_looks=self.look_counter_true, 
#                 #                              total_false_looks=self.look_counter_false, 
#                 #                              change_of_position=self.position_counter, 
#                 #                              total_skips=self.skipped_counter, 
#                 #                              conversation_data=interaction_data)
#                 return result
#             self.publish_feedback(goal_handle=goal_handle, output_text=text_to_speak)
#             interaction_data.append(["", text_to_speak])
#             state = "SPEAK"
#             validated = True

#             #TODO: load pairs of step-expected visual response as A FIFO queue, from where?

#             i = 0
#             while rclpy.ok():
#                 step, instruction, expected_result = control_steps[i] 
#                 if goal_handle.is_cancel_requested:
#                     if self.debug:
#                         self.get_logger().info('Received cancel goal handle conversation server...')
#                     self.cancel_all_children()
#                     goal_handle.canceled()
#                     self.input_cancel_pending=False
#                     self.output_cancel_pending=False
#                     self._active_goal_handle = None
#                     self.get_logger().info('Ending goal as canceled...')
#                     # end_time = time.time()
#                     # total_duration = round(end_time - start_time, 2)
#                     # if self.get_parameter("save_conversation").value:
#                     #     file_name = f'{self.get_parameter("id_experiment").value}_'
#                     #     self.get_logger().info('Saving new conversation file: ' + (file_name))
#                     #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
#                     #                                 total_duration=total_duration, 
#                     #                                 total_true_looks=self.look_counter_true, 
#                     #                                 total_false_looks=self.look_counter_false, 
#                     #                                 change_of_position=self.position_counter, 
#                     #                                 total_skips=self.skipped_counter, 
#                     #                                 conversation_data=interaction_data)
#                     return result
                
#                 # with self.skip_lock:
#                 #     if self.is_skipped: 
#                 #         state="LISTEN"
#                 #         if self.debug:
#                 #             self.get_logger().info("Conversation skipped, going back to listen state...")
#                 #         self.is_skipped = False

#                 if state == "LISTEN":
#                     self.publish_feedback(goal_handle=goal_handle, state_string="Listening")
#                     if self.debug:
#                         self.get_logger().info('Send goal to input server...')

#                     success, input = await self.handle_input(goal_handle)
#                     if not success:
#                         if self.debug:
#                             self.get_logger().info('Input goal not success...')
#                         self.cancel_all_children()
#                         goal_handle.canceled()
#                         self._active_goal_handle = None
#                         self.input_cancel_pending=False
#                         self.output_cancel_pending=False
#                         self.get_logger().info('Ending goal as canceled...')
#                         # end_time = time.time()
#                         # total_duration = round(end_time - start_time, 2)
#                         # if self.get_parameter("save_conversation").value:
#                         #     file_name = f'{self.get_parameter("id_experiment").value}_'
#                         #     self.get_logger().info('Saving new conversation file: ' + (file_name))
#                         #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
#                         #                              total_duration=total_duration, 
#                         #                              total_true_looks=self.look_counter_true, 
#                         #                              total_false_looks=self.look_counter_false, 
#                         #                              change_of_position=self.position_counter, 
#                         #                              total_skips=self.skipped_counter, 
#                         #                              conversation_data=interaction_data)
#                         return result
#                     if input == "offconv":
#                         if self.debug:
#                             self.get_logger().info("Received 'offconv' command, listening again...")
#                         state = "LISTEN"
#                     else: #Looking and input received
#                         if self.debug:
#                             self.get_logger().info("Received input, validating...")
#                         self.publish_feedback(goal_handle=goal_handle, input_text=input)
#                         state = "VALIDATE"

#                 elif state == "VALIDATE":
#                     self.publish_feedback(goal_handle=goal_handle, state_string="Validating")
#                     if self.debug:
#                         self.get_logger().info('Validating input...')
#                     await asyncio.sleep(2) # Simulate validation time

#                     # (result call validate )

#                     # TODO: implement call to action validate
#                     if result == expected_result:
#                         validated = True
#                         i +=1 
#                         self.publish_feedback(goal_handle=goal_handle, state_string="Action validated")
#                     else:
#                         validated = False
#                     state = "SPEAK"

#                 elif state == "SPEAK":
#                     self.publish_feedback(goal_handle=goal_handle, state_string="Speaking")
#                     if self.debug:
#                         self.get_logger().info('Send goal to output server...')
#                     if not validated:
#                         text_to_speak = "The action has not been correctly validated. Check again and onfirm whenever you want me to check. " 
#                     else:
#                         text_to_speak = instruction 
#                     success = await self.handle_output(goal_handle,
#                                                     text= text_to_speak, 
#                                                     use_text_field = True)
#                     if not success:
#                         if self.debug:
#                             self.get_logger().info('Output goal not success...')
#                         self.cancel_all_children()
#                         goal_handle.canceled()
#                         self._active_goal_handle = None
#                         self.input_cancel_pending=False
#                         self.output_cancel_pending=False
#                         self.get_logger().info('Ending goal as canceled...')
#                         # end_time = time.time()
#                         # total_duration = round(end_time - start_time, 2)
#                         # if self.get_parameter("save_conversation").value:
#                         #     file_name = f'{self.get_parameter("id_experiment").value}_{self.interaction_order}_S{self.get_parameter("system").value}_P{self.get_parameter("patient").value}'
#                         #     self.get_logger().info('Saving new conversation file: ' + (file_name))
#                         #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
#                         #                              total_duration=total_duration, 
#                         #                              total_true_looks=self.look_counter_true, 
#                         #                              total_false_looks=self.look_counter_false, 
#                         #                              change_of_position=self.position_counter, 
#                         #                              total_skips=self.skipped_counter, 
#                         #                              conversation_data=interaction_data)
#                         return result
#                     self.publish_feedback(goal_handle=goal_handle, output_text=text_to_speak)
#                     interaction_data.append(["", text_to_speak])
#                     state = "LISTEN"
#                 #self.output_dialog.value.string_value = ""
#                 # self.get_logger().info("Previous dialog: \n\n" + json.dumps(interaction_data)   ) 
#                 time.sleep(0.01)

#         elif mode == "corrector":

#             # TODO: implement logic    
#             if self.get_parameter("instructions").value: #Start with instructions
#                 self.publish_feedback(goal_handle=goal_handle, state_string="Speaking")
#                 await self.send_instructions(goal_handle, self.instructions_text)
#                 state = "LISTEN" #TODO: implement to wait for confirmation of starting
#             else:
#                 text_to_speak= "We will start the task. Okay?"
#                 state="SPEAK" #TODO: implement to wait for confirmation of starting

#             #TODO: load pairs of step-expected visual response as A FIFO queue, from where? from a json?
#             #If we start the whole process every time, we have to set a parameter from goal as with mode, no?
#             validation_steps =  deque([
#                     ("phase1 group 1", "expected1"),
#                     ("phase2 group 1", "expected2"),
#                     ("phase3 group 1", "expected3"),    
#                     ("phase1 group 2", "expected4"),
#                     ("phase2 group 2", "expected5"),
#                     ("phase3 group 2", "expected6"),
#                     ("phase1 group 3", "expected7"),
#                     ("phase2 group 3", "expected8"),
#                     ("phase3 group 3", "expected9"),
#                 ])

#             i = 0
#             end_loop = False
#             while rclpy.ok() and not end_loop:
#                 phase, expected_result = validation_steps[i] 
#                 if goal_handle.is_cancel_requested:
#                     if self.debug:
#                         self.get_logger().info('Received cancel goal handle conversation server...')
#                     self.cancel_all_children()
#                     goal_handle.canceled()
#                     self.input_cancel_pending=False
#                     self.output_cancel_pending=False
#                     self._active_goal_handle = None
#                     self.get_logger().info('Ending goal as canceled...')
#                     # end_time = time.time()
#                     # total_duration = round(end_time - start_time, 2)
#                     # if self.get_parameter("save_conversation").value:
#                     #     file_name = f'{self.get_parameter("id_experiment").value}_'
#                     #     self.get_logger().info('Saving new conversation file: ' + (file_name))
#                     #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
#                     #                                 total_duration=total_duration, 
#                     #                                 total_true_looks=self.look_counter_true, 
#                     #                                 total_false_looks=self.look_counter_false, 
#                     #                                 change_of_position=self.position_counter, 
#                     #                                 total_skips=self.skipped_counter, 
#                     #                                 conversation_data=interaction_data)
#                     return result
                
#                 # TODO: check visual situation feedback with expected result
#                 # TODO: put a locker for checking this variable
#                 # if self.vision_feedback == expected_result:
#                 #     validated = True
#                 # else:
#                 #     validated = False
#                 #     continue

#                 # with self.skip_lock:
#                 #     if self.is_skipped: 
#                 #         state="LISTEN"
#                 #         if self.debug:
#                 #             self.get_logger().info("Conversation skipped, going back to listen state...")
#                 #         self.is_skipped = False

#                 if state == "LISTEN":
#                     self.publish_feedback(goal_handle=goal_handle, state_string="Listening")
#                     if self.debug:
#                         self.get_logger().info('Send goal to input server...')

#                     success, input = await self.handle_input(goal_handle)
#                     if not success:
#                         if self.debug:
#                             self.get_logger().info('Input goal not success...')
#                         self.cancel_all_children()
#                         goal_handle.canceled()
#                         self._active_goal_handle = None
#                         self.input_cancel_pending=False
#                         self.output_cancel_pending=False
#                         self.get_logger().info('Ending goal as canceled...')
#                         # end_time = time.time()
#                         # total_duration = round(end_time - start_time, 2)
#                         # if self.get_parameter("save_conversation").value:
#                         #     file_name = f'{self.get_parameter("id_experiment").value}_'
#                         #     self.get_logger().info('Saving new conversation file: ' + (file_name))
#                         #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
#                         #                              total_duration=total_duration, 
#                         #                              total_true_looks=self.look_counter_true, 
#                         #                              total_false_looks=self.look_counter_false, 
#                         #                              change_of_position=self.position_counter, 
#                         #                              total_skips=self.skipped_counter, 
#                         #                              conversation_data=interaction_data)
#                         return result
#                     if input == "offconv":
#                         if self.debug:
#                             self.get_logger().info("Received 'offconv' command, listening again...")
#                         state = "LISTEN"
#                     else: #Looking and input received
#                         if self.debug:
#                             self.get_logger().info("Received input, validating...")
#                         self.publish_feedback(goal_handle=goal_handle, input_text=input)
#                         state = "VALIDATE"

#                 elif state == "VALIDATE":
#                     # TODO: implement call to function validate goal.
#                     self.publish_feedback(goal_handle=goal_handle, state_string="Validating")
#                     if self.debug:
#                         self.get_logger().info('Validating input...')
#                     await asyncio.sleep(2) # Simulate validation time

#                     # (rerror_msg, success call validate )
#                     # si es error, el error msg ha de ser els valors dela validaci explicant on ha fallat, success un bool de si sha validat o no
                    
#                     error_msg = ""
#                     state = "SPEAK"

#                 elif state == "SPEAK":
#                     self.publish_feedback(goal_handle=goal_handle, state_string="Speaking")
#                     if self.debug:
#                         self.get_logger().info('Send goal to output server...')
                    
#                     if not success:
#                         text_to_speak = "Something is wrong: " + error_msg + ". Please correct it."
#                     else: 
#                         if i == len(validation_steps):
#                             text_to_speak = "Everything is correct. You are done with this phase."
#                             end_loop = True
#                         else:
#                             text_to_speak = "Everything is correct. Proceed to the next phase and tell me when you are ready to check again."
#                     success = await self.handle_output(goal_handle,
#                                                     text= text_to_speak,  #TODO: DEFINE text to speak following the continuation of the steps.
#                                                     use_text_field = True)
#                     if not success:
#                         if self.debug:
#                             self.get_logger().info('Output goal not success...')
#                         self.cancel_all_children()
#                         goal_handle.canceled()
#                         self._active_goal_handle = None
#                         self.input_cancel_pending=False
#                         self.output_cancel_pending=False
#                         self.get_logger().info('Ending goal as canceled...')
#                         # end_time = time.time()
#                         # total_duration = round(end_time - start_time, 2)
#                         # if self.get_parameter("save_conversation").value:
#                         #     file_name = f'{self.get_parameter("id_experiment").value}_{self.interaction_order}_S{self.get_parameter("system").value}_P{self.get_parameter("patient").value}'
#                         #     self.get_logger().info('Saving new conversation file: ' + (file_name))
#                         #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
#                         #                              total_duration=total_duration, 
#                         #                              total_true_looks=self.look_counter_true, 
#                         #                              total_false_looks=self.look_counter_false, 
#                         #                              change_of_position=self.position_counter, 
#                         #                              total_skips=self.skipped_counter, 
#                         #                              conversation_data=interaction_data)
#                         return result
#                     self.publish_feedback(goal_handle=goal_handle, output_text=text_to_speak)
#                     interaction_data.append(["", text_to_speak])
#                     state = "LISTEN"
#                 #self.output_dialog.value.string_value = ""
#                 # self.get_logger().info("Previous dialog: \n\n" + json.dumps(interaction_data)   ) 
#                 time.sleep(0.01)


















#         goal_handle.succeed()
#         self._active_goal_handle = None
#         self.input_cancel_pending=False
#         self.output_cancel_pending=False
#         self.get_logger().info('Ending succeed goal...')
#         # end_time = time.time()
#         # total_duration = round(end_time - start_time, 2)
#         # if self.get_parameter("save_conversation").value:
#         #     file_name = f'{self.get_parameter("id_experiment").value}_{self.interaction_order}_S{self.get_parameter("system").value}_P{self.get_parameter("patient").value}'
#         #     self.get_logger().info('Saving new conversation file: ' + (file_name))
#         #     self.write_conversations(file_path=(self.get_parameter("directory").value+"/"+file_name), 
#         #                                 total_duration=total_duration, 
#         #                                 total_true_looks=self.look_counter_true, 
#         #                                 total_false_looks=self.look_counter_false, 
#         #                                 change_of_position=self.position_counter, 
#         #                                 total_skips=self.skipped_counter, 
#         #                                 conversation_data=interaction_data)
#         return result

#     def goal_callback(self, goal_request):
#         '''
#         Accepts or rejects a client request to begin an action.
#         '''
#         self.get_logger().info('Received goal request')
#         return GoalResponse.ACCEPT
    
#     def cancel_callback(self, goal_handle):

#         self.get_logger().info("Received conversation cancel request")
#         self.cancel_all_children()

#         return CancelResponse.ACCEPT
    
#     def cancel_all_children(self):

#         self.input_cancel_pending=True
#         self.output_cancel_pending=True

#         if self.current_input_goal is not None:
#             self.get_logger().info("Cancelling input goal")
#             self.current_input_goal.cancel_goal_async()
#             self.input_cancel_pending=False

#         if self.current_output_goal is not None:
#             self.get_logger().info("Cancelling TTS goal")
#             self.current_output_goal.cancel_goal_async()
#             self.output_cancel_pending=False
    
#     async def handle_input(self, goal_handle, listen_time=0):

#         if goal_handle.is_cancel_requested:
#             return False, ""

#         input_goal = Input.Goal(listen_time=listen_time)

#         self.current_input_goal = await self.input_client.send_goal_async(input_goal)

#         if not self.current_input_goal.accepted:
#             return False, ""

#         result_future = await self.current_input_goal.get_result_async()
#         self.current_input_goal = None

#         if goal_handle.is_cancel_requested:
#             return False, ""
        
#         return True, result_future.result.user_input
    
#     async def handle_output(self, goal_handle, text, use_text_field):
#         """
#         Trigger Output goal.
#         """
#         if goal_handle.is_cancel_requested:
#             return False, ""
        
#         # Output
#         output_goal = Output.Goal(text=text, use_text_field=use_text_field)
#         self.current_output_goal = await self.output_client.send_goal_async(
#             output_goal
#         )

#         if not self.current_output_goal.accepted:
#             self.current_output_goal = None
#             return False, ""
        
#         await self.current_output_goal.get_result_async()
#         self.current_output_goal = None

#         if goal_handle.is_cancel_requested:
#             return False, ""
        
#         return True

#     # async def handle_think_and_output(self, goal_handle, model, messages, text, use_text_field):
#     #     """
#     #     Trigger both LLM and Output goals concurrently.
#     #     """
#     #     if goal_handle.is_cancel_requested:
#     #         return False, ""
        
#     #     # Output: send first goal to flush queue before LLM generated answers to add to queue
#     #     output_goal = Output.Goal(text=text, use_text_field=use_text_field)
#     #     self.current_output_goal = await self.output_client.send_goal_async(
#     #         output_goal
#     #     )

#     #     if not self.current_output_goal.accepted:
#     #         self.current_output_goal = None
#     #         return False, ""

#     #     # LLM
#     #     llm_goal = Llm.Goal(model=model, messages=messages) #TODO: change it to prompt
#     #     self.current_llm_goal = await self.llm_client.send_goal_async(
#     #         llm_goal,
#     #         feedback_callback=self.llm_feedback_callback
#     #     )

#     #     if not self.current_llm_goal.accepted:
#     #         self.current_llm_goal = None
#     #         return False, ""
        
#     #     if goal_handle.is_cancel_requested:
#     #         return False, ""

#     #     # Wait LLM response
#     #     llm_result_future = await self.current_llm_goal.get_result_async()
#     #     self.current_llm_goal = None

#     #     if self.debug:
#     #         self.get_logger().info('Future llm goal finished')

#     #     if goal_handle.is_cancel_requested:
#     #         return False, ""
        
#     #     await self.current_output_goal.get_result_async()
#     #     self.current_output_goal = None

#     #     if self.debug:
#     #         self.get_logger().info('Future output goal finished')
        
#     #     if goal_handle.is_cancel_requested:
#     #         return False, ""
        
#     #     return True, llm_result_future.result.final_text

#     # def skip_callback(self, request, response):
#     #     self.skipped_counter+= 1
#     #     #if self.debug:
#     #     self.get_logger().info("Received skip service request, cancelling all goals...")
#     #     self.cancel_all_children()
#     #     self.input_cancel_pending = False
#     #     self.output_cancel_pending = False
#     #     self.is_skipped = True
#     #     return response
    
#     async def send_instructions(self,goal_handle, text):

#         paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

#         for paragraph in paragraphs:
#             if self.debug:
#                 self.get_logger().info(f"Sending instructions paragraph: {paragraph}")
#             success = await self.handle_output(goal_handle,
#                                     text= paragraph,
#                                     use_text_field = True)
#             #await asyncio.sleep(3)
    
#     def publish_feedback(
#         self,
#         goal_handle,
#         state_string: str = None,
#         input_text: str = None,
#         output_text: str = None,
#         move_value: bool = None
#     ):
        
#         feedback_msg = Conversation.Feedback()
#         feedback_msg.feedback = []

#         if state_string is not None:
#             state_msg = Parameter()
#             state_msg.name = "feedback_state"
#             state_msg.value.type = 4
#             state_msg.value.string_value = state_string
#             feedback_msg.feedback.append(state_msg)

#         if input_text is not None:
#             input_dialog = Parameter()
#             input_dialog.name = "input_dialog"
#             input_dialog.value.type = 4
#             input_dialog.value.string_value = input_text
#             feedback_msg.feedback.append(input_dialog)

#         if output_text is not None:
#             output_dialog = Parameter()
#             output_dialog.name = "output_dialog"
#             output_dialog.value.type = 4
#             output_dialog.value.string_value = output_text
#             feedback_msg.feedback.append(output_dialog)
        
#         # Adapt as needed depending on the flags

#         # if move_value is not None:
#         #     move_msg = Parameter()
#         #     move_msg.name = "go_to_person"
#         #     move_msg.value.type = 1
#         #     move_msg.value.bool_value = move_value
#         #     feedback_msg.feedback.append(move_msg)

#         # Only publish if something was actually added
#         if feedback_msg.feedback:
#             goal_handle.publish_feedback(feedback_msg)

#     # def write_conversations(self, file_path, 
#     #                     total_duration, 
#     #                     total_true_looks, 
#     #                     total_false_looks, 
#     #                     change_of_position, 
#     #                     total_skips, 
#     #                     conversation_data):
#     #     # First pair of conversation_data is ('', greeting assistant)
#     #     num_questions=0
#     #     num_answers=0
#     #     try:
#     #         with open(file_path, "w") as file:
#     #             # Iterate over each (user, assistant) pair
#     #             file.write(f"Total duration: {total_duration:.2f} seconds\n")
#     #             file.write(f"Total true looks: {total_true_looks}\n")
#     #             file.write(f"Total false looks: {total_false_looks}\n")
#     #             file.write(f"Change of position: {change_of_position}\n")
#     #             file.write(f"Total skips: {total_skips}\n")
#     #             for user_text, assistant_text in conversation_data:
#     #                 # Write user dialog
#     #                 if user_text and user_text.strip():
#     #                     num_questions+=1
#     #                 # Write assistant dialog
#     #                 if assistant_text and assistant_text.strip():
#     #                     num_answers+=1
#     #             file.write(f"Total inputs: {num_questions}\n")
#     #             file.write(f"Total outputs: {num_answers}\n")
#     #             file.write("---------------------------------\n")
#     #             file.write("TOTAL CONVERSATION  \n")

#     #             for user_text, assistant_text in conversation_data:
#     #                 # Write user dialog
#     #                 if user_text and user_text.strip():
#     #                     file.write(f"User: {user_text}\n")
#     #                 # Write assistant dialog
#     #                 if assistant_text and assistant_text.strip():
#     #                     file.write(f"Assistant: {assistant_text}\n")
#     #         return True
#     #     except ValueError as e:
#     #         return f"Error: {e}"

# def main(args=None):
#     rclpy.init(args=args)

#     conversation = TriageServer()
#     executor = MultiThreadedExecutor(4)
#     executor.add_node(conversation)
#     executor.spin()

#     conversation.get_logger().info('Destroying node...')
#     conversation.destroy_node()
#     rclpy.shutdown()

# if __name__ == '__main__':
#     main()

