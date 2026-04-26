# -*- coding: utf-8 -*-
"""
Triage Game — ROS 2 Node
=========================
Two learning modes:
  guided_learning  — robot guides one slot at a time, auto-advances on correct
  error_based      — participant places all 5, says "validate", robot corrects

Integration points for the robotics team are marked with:
  ── INTEGRATION POINT ──

Usage:
  ros2 run triage_pkg triage_game_node \
    --ros-args -p mode:=error_based -p set:=A -p language:=en
"""

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient

# ── INTEGRATION POINT 1 ───────────────────────────────────────────────────────
# Import PARLAM action types.
# Replace with the actual package and action names used by the PARLAM team.
# Expected interface:
#   SpeechInput.Goal:   listen_time (float)
#   SpeechInput.Result: user_input (str) — returns "offconv" if nothing heard
#   SpeechOutput.Goal:  use_text_field (bool), text (str)
#   SpeechOutput.Result: (success signal — content not used)
from parlam_interfaces.action import SpeechInput, SpeechOutput
# ─────────────────────────────────────────────────────────────────────────────

# ── INTEGRATION POINT 2 ───────────────────────────────────────────────────────
# Camera message type.
# Replace Image with the correct message type if different.
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
# ─────────────────────────────────────────────────────────────────────────────

import cv2
import cv2.aruco as aruco
import numpy as np
from collections import deque, Counter
import threading
import time

from game_engine import GameEngine, Phase


# ── INTEGRATION POINT 3 ───────────────────────────────────────────────────────
# ArUco dictionary and slot mapping.
# Confirm DICT_4X4_100 is the dictionary used for the physical patient cards.
# Corner IDs 0-3 are the board boundary markers.
# Patient cards: Set A = IDs 10-24, Set B = IDs 40-54.
ARUCO_DICT   = aruco.getPredefinedDictionary(aruco.DICT_4X4_100)
ARUCO_PARAMS = aruco.DetectorParameters()
CORNER_IDS   = {0, 1, 2, 3}
MAJORITY_WINDOW = 10  # number of frames for majority vote before confirming a card
# ─────────────────────────────────────────────────────────────────────────────


class SlotDetector:
    """
    Detects which patient card (ArUco ID) is in each of the 5 board slots.
    Uses the 4 corner markers to define the board boundaries, then assigns
    patient cards to slots by position.
    Uses majority vote over MAJORITY_WINDOW frames to avoid flicker.
    """

    def __init__(self):
        self._history = {s: deque(maxlen=MAJORITY_WINDOW) for s in range(1, 6)}

    def update(self, corners, ids):
        """
        corners: output of aruco.detectMarkers
        ids:     flat list of detected marker IDs
        Returns: dict {slot_num (1-5): aruco_id} for confirmed cards
        """
        if ids is None or len(ids) == 0:
            for s in range(1, 6):
                self._history[s].append(None)
            return {}

        id_to_center = {}
        for i, marker_id in enumerate(ids):
            c = corners[i][0]
            cx = float(np.mean(c[:, 0]))
            cy = float(np.mean(c[:, 1]))
            id_to_center[int(marker_id)] = (cx, cy)

        # ── INTEGRATION POINT 4 ───────────────────────────────────────────────
        # Slot assignment from ArUco position.
        # The current implementation uses a simplified column-based assignment.
        # The robotics team should replace this with a proper homography-based
        # mapping using the 4 corner markers (IDs 0-3) to compute exact slot
        # positions on the physical board.
        patient_markers = {k: v for k, v in id_to_center.items()
                           if k not in CORNER_IDS}
        slots = {}
        if patient_markers:
            all_x = [v[0] for v in patient_markers.values()]
            min_x, max_x = min(all_x), max(all_x)
            width = max(max_x - min_x, 1)
            for marker_id, (cx, cy) in patient_markers.items():
                col  = min(4, int(((cx - min_x) / width) * 5))
                slot = col + 1
                slots[slot] = marker_id
        # ─────────────────────────────────────────────────────────────────────

        for slot in range(1, 6):
            self._history[slot].append(slots.get(slot))

        confirmed = {}
        for slot in range(1, 6):
            hist = [v for v in self._history[slot] if v is not None]
            if len(hist) >= MAJORITY_WINDOW // 2:
                confirmed[slot] = Counter(hist).most_common(1)[0][0]

        return confirmed


class TriageGameNode(Node):

    def __init__(self):
        super().__init__('triage_game_node')

        # Parameters (set via --ros-args -p name:=value)
        self.declare_parameter('mode',         'error_based')
        self.declare_parameter('set',          'A')
        self.declare_parameter('language',     'en')
        self.declare_parameter('listen_time',  8.0)

        # ── INTEGRATION POINT 5 ───────────────────────────────────────────────
        # Camera topic name. Confirm with:  ros2 topic list | grep image
        self.declare_parameter('camera_topic', '/xtion/rgb/image_raw')
        # ─────────────────────────────────────────────────────────────────────

        # ── INTEGRATION POINT 6 ───────────────────────────────────────────────
        # Action server names. Confirm with: ros2 action list
        self.declare_parameter('speech_input_action',  'speech_input_action')
        self.declare_parameter('speech_output_action', 'speech_output_action')
        # ─────────────────────────────────────────────────────────────────────

        mode      = self.get_parameter('mode').value
        set_label = self.get_parameter('set').value
        language  = self.get_parameter('language').value
        cam_topic = self.get_parameter('camera_topic').value
        in_action = self.get_parameter('speech_input_action').value
        out_action= self.get_parameter('speech_output_action').value

        # Game engine (no LLM — fully rules-based)
        self.engine = GameEngine(
            set_label=set_label,
            mode=mode,
            language=language,
        )

        # Camera subscriber
        self.bridge        = CvBridge()
        self.slot_detector = SlotDetector()
        self._last_board   = {}
        self._cam_lock     = threading.Lock()
        self.cam_sub = self.create_subscription(
            Image, cam_topic, self._camera_cb, 10)

        # PARLAM action clients
        self._speech_input  = ActionClient(self, SpeechInput,  in_action)
        self._speech_output = ActionClient(self, SpeechOutput, out_action)

        # State flags — prevent overlapping speak/listen calls
        self._speaking  = False
        self._listening = False

        # Main loop: runs every 100ms
        self._main_timer = self.create_timer(0.1, self._tick)

        self.get_logger().info(
            f"TriageGameNode ready | mode={mode} set={set_label} lang={language} "
            f"camera={cam_topic}")

        # Start iteration 1 automatically
        self._start_iteration(1)

    # ─── CAMERA ───────────────────────────────────────────────────────────────
    def _camera_cb(self, msg):
        """Receive camera frame, detect ArUco markers, update board state."""
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
        except Exception as e:
            self.get_logger().warn(f"CvBridge error: {e}")
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = aruco.detectMarkers(
            gray, ARUCO_DICT, parameters=ARUCO_PARAMS)
        flat_ids = [int(i[0]) for i in ids] if ids is not None else []

        board = self.slot_detector.update(corners, flat_ids)
        with self._cam_lock:
            self._last_board = board

    def _get_board(self):
        with self._cam_lock:
            return dict(self._last_board)

    # ─── MAIN TICK ────────────────────────────────────────────────────────────
    def _tick(self):
        """
        Called every 100ms.
        Feeds current board state to the engine and processes any resulting actions.
        Does nothing while the robot is speaking or listening.
        """
        if self._speaking or self._listening:
            return

        board = self._get_board()
        if board:
            actions = self.engine.update(board)
            self._process_actions(actions)

    # ─── ENGINE ACTION PROCESSING ─────────────────────────────────────────────
    def _process_actions(self, actions):
        """Dispatch actions emitted by the game engine."""
        for action in actions:
            atype = action.get('type')

            if atype == 'speak':
                self._speak(action['text'])

            elif atype == 'listen':
                duration = action.get('duration',
                           self.get_parameter('listen_time').value)
                self._listen(duration)

            elif atype == 'log':
                self.get_logger().info(
                    f"[LOG] {action.get('phase')} "
                    f"attempt {action.get('attempt','?')}: "
                    f"{action.get('score','?')}")

            elif atype == 'end_iteration':
                self.get_logger().info(
                    f"[GAME] Iteration complete: {action.get('summary',{})}")
                self._on_iteration_complete()

            elif atype == 'state_change':
                self.get_logger().info(f"[STATE] → {action.get('phase')}")

    # ─── SPEECH OUTPUT ────────────────────────────────────────────────────────
    def _speak(self, text: str):
        """
        Send text to PARLAM speech output action server.
        Blocks further ticks until speaking is done.
        """
        if not self._speech_output.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn("Speech output server not available — skipping")
            return

        self._speaking = True
        goal = SpeechOutput.Goal()

        # ── INTEGRATION POINT 7 ───────────────────────────────────────────────
        # PARLAM speech output goal fields.
        # Mode A (direct text): set use_text_field=True and text=...
        # Mode B (LLM streaming via /output_text topic): not used here.
        # Confirm field names with PARLAM team.
        goal.use_text_field = True
        goal.text = text
        # ─────────────────────────────────────────────────────────────────────

        self.get_logger().info(f"[SPEAK] {text[:80]}{'...' if len(text)>80 else ''}")
        future = self._speech_output.send_goal_async(goal)
        future.add_done_callback(self._speak_goal_cb)

    def _speak_goal_cb(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warn("Speech output goal rejected")
            self._speaking = False
            return
        goal_handle.get_result_async().add_done_callback(self._speak_result_cb)

    def _speak_result_cb(self, future):
        self._speaking = False
        self.get_logger().info("[SPEAK] Done")

    # ─── SPEECH INPUT ─────────────────────────────────────────────────────────
    def _listen(self, duration: float = 8.0):
        """
        Send listen goal to PARLAM speech input action server.
        On result, passes recognised text to engine.on_speech().
        """
        if not self._speech_input.wait_for_server(timeout_sec=2.0):
            self.get_logger().warn("Speech input server not available — skipping")
            return

        self._listening = True
        goal = SpeechInput.Goal()

        # ── INTEGRATION POINT 8 ───────────────────────────────────────────────
        # PARLAM speech input goal fields.
        # Confirm field name (listen_time or similar) with PARLAM team.
        goal.listen_time = duration
        # ─────────────────────────────────────────────────────────────────────

        self.get_logger().info(f"[LISTEN] Waiting up to {duration}s...")
        future = self._speech_input.send_goal_async(goal)
        future.add_done_callback(self._listen_goal_cb)

    def _listen_goal_cb(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warn("Speech input goal rejected")
            self._listening = False
            return
        goal_handle.get_result_async().add_done_callback(self._listen_result_cb)

    def _listen_result_cb(self, future):
        # ── INTEGRATION POINT 9 ───────────────────────────────────────────────
        # PARLAM speech input result field.
        # Confirm field name (user_input or similar) with PARLAM team.
        # "offconv" is returned when nothing was heard.
        result = future.result().result
        text   = result.user_input.strip().lower()
        # ─────────────────────────────────────────────────────────────────────

        self._listening = False
        self.get_logger().info(f"[LISTEN] Heard: '{text}'")

        if text and text != 'offconv':
            actions = self.engine.on_speech(text)
            self._process_actions(actions)

    # ─── HEAD MOTION ──────────────────────────────────────────────────────────
    # ── INTEGRATION POINT 10 ──────────────────────────────────────────────────
    # TIAGo head motion (look at board, look at participant, nod, etc.).
    # The robotics team should implement this using the ROS 1 bridge or
    # the TIAGo head controller action server.
    # Example call sites:
    #   - When announcing a slot: look at the board
    #   - When speaking to participant: look at participant
    #   - When correct: nod
    # Placeholder:
    def _move_head(self, target: str):
        """
        target: 'board' | 'participant' | 'nod'
        Replace with actual TIAGo head controller calls.
        """
        self.get_logger().info(f"[HEAD] → {target}  (placeholder — not implemented)")
    # ─────────────────────────────────────────────────────────────────────────

    # ─── ITERATION MANAGEMENT ─────────────────────────────────────────────────
    def _start_iteration(self, iteration: int):
        self.get_logger().info(f"[GAME] Starting iteration {iteration}")
        actions = self.engine.start_iteration(iteration)
        self._process_actions(actions)

    def _on_iteration_complete(self):
        """Move to next iteration (up to 3) or end session."""
        current = self.engine.iteration
        if current < 3:
            self.get_logger().info(f"[GAME] Moving to iteration {current + 1}")
            self._start_iteration(current + 1)
        else:
            self.get_logger().info("[GAME] All 3 iterations complete")
            log_path = f"/tmp/triage_session_{int(time.time())}.json"
            self.engine.save_session_log(log_path)
            self.get_logger().info(f"[GAME] Session log saved to {log_path}")

            farewell = ("Well done! The session is complete. Thank you."
                        if self.engine.language == 'en'
                        else "¡Bien hecho! La sesión ha terminado. Gracias.")
            self._speak(farewell)


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
def main(args=None):
    rclpy.init(args=args)
    node = TriageGameNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
