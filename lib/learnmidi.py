import pickle
import numpy as np
from lib.music_splitter import MidiMessageWithTime, MusicSplitter, still_notes_in_chord
from lib.neopixel import getRGB, Color
from lib.functions import clamp, fastColorWipe, changeAllLedsColor, midi_note_num_to_string, set_read_only, setLedPattern, find_between, get_note_position, get_key_color, touch_file, read_only_fs
from copy import deepcopy
import ast
import threading
import time
import traceback

import mido
import re
import os
import queue
import subprocess
import codecs

DEBUG = False

TRASPOSE_LEARNING = 0

if DEBUG:
    import ipdb

# lengt
CACHE_VERSION = 37


def find_nearest(array, target):
    array = np.asarray(array)
    idx = (np.abs(array - target)).argmin()
    return idx


PRACTICE_MELODY = 0
PRACTICE_RHYTHM = 1
PRACTICE_LISTEN = 2
PRACTICE_ARCADE = 3
PRACTICE_PROGRESSIVE = 4
PRACTICE_PERFECTION = 5

LOWEST_LED_BRIGHT = 5
MIDDLE_LED_BRIGHT = 32
MAX_LED_BRIGHT = 255
SWITCH_OFF_DELAY = 0.5


class LearnMIDI:
    def __init__(self, usersettings, ledsettings, midiports, ledstrip):
        self.usersettings = usersettings
        self.ledsettings = ledsettings
        self.midiports = midiports
        self.ledstrip = ledstrip
        self.traspose = 0

        self.loading = 0
        self.practice = int(usersettings.get_setting_value("practice"))
        self.hands = int(usersettings.get_setting_value("hands"))
        self.mute_hand = int(usersettings.get_setting_value("mute_hand"))
        self.start_point = int(usersettings.get_setting_value("start_point"))
        self.end_point = int(usersettings.get_setting_value("end_point"))
        self.set_tempo = int(usersettings.get_setting_value("set_tempo"))
        self.hand_colorR = int(usersettings.get_setting_value("hand_colorR"))
        self.hand_colorL = int(usersettings.get_setting_value("hand_colorL"))
        self.learn_step = int(usersettings.get_setting_value("learn_step"))

        self.socket_send = []
        self.bookmarks = set()

        self.is_loop_active = int(
            usersettings.get_setting_value("is_loop_active"))

        self.loadingList = ['', 'Load..', 'Proces', 'Merge', 'Done', 'Error!']
        self.practiceList = ['Melody', 'Rhythm', 'Listen',
                             'Arcade', 'Progressive', 'Perfection']
        self.learnStepList = ['1/1', '1/2', '1/3', '1/4', '1/∞',
                              '2/1', '2/2', '2/3', '2/4', '2/∞',
                              '3/1', '3/2', '3/3', '3/4', '3/∞',
                              '4/1', '4/2', '4/3', '4/4', '4/∞',
                              '5/1', '5/2', '5/3', '5/4', '5/∞',
                              '6/1', '6/2', '6/3', '6/4', '6/∞',
                              '7/1', '7/2', '7/3', '7/4', '7/∞']
        self.handsList = ['Both', 'Right', 'Left']
        self.mute_handList = ['Off', 'Right', 'Left']
        self.hand_colorList = ast.literal_eval(
            usersettings.get_setting_value("hand_colorList"))

        self.song_tempo = 500000
        self.song_tracks: list[MidiMessageWithTime] = []
        self.ticks_per_beat = 240
        self.loaded_midi = None
        self.is_started_midi = False
        self.t = None
        self.current_measure = -1
        self.total_wait_time = 0.0
        self.wrong_keys = 0
        self.learning_midi = False
        self.current_score = 0
        self.blind_mode = False
        self.is_read_only_fs = read_only_fs()
        self.midi_messages = queue.Queue()
        self.prev_score = None
        self.prev_wrong = None
        self.listen_again = False
        if self.is_read_only_fs:
            print("Read only FS")

    def add_instance(self, menu):
        self.menu = menu

    def change_practice(self, value):
        self.practice += value
        self.practice = clamp(self.practice, 0, len(self.practiceList) - 1)
        self.usersettings.change_setting_value("practice", self.practice)

    def change_hands(self, value):
        self.hands += value
        self.hands = clamp(self.hands, 0, len(self.handsList) - 1)
        self.usersettings.change_setting_value("hands", self.hands)

    def change_mute_hand(self, value):
        self.mute_hand += value
        self.mute_hand = clamp(self.mute_hand, 0, len(self.mute_handList) - 1)
        self.usersettings.change_setting_value("mute_hand", self.mute_hand)

    def restart_learning(self):
        if self.is_started_midi:
            self.is_started_midi = False
            if self.t is not None:
                self.t.join()
            self.t = threading.Thread(target=self.learn_midi)
            self.t.start()

    def change_start_point(self, value):
        self.start_point += value
        self.start_point = clamp(self.start_point, 1, self.end_point - 1)
        self.usersettings.change_setting_value("start_point", self.start_point)
        self.restart_learning()

    def change_learn_step(self, value):
        self.learn_step += value
        self.learn_step = clamp(
            self.learn_step, 1, len(self.learnStepList) - 1)
        self.usersettings.change_setting_value("learn_step", self.learn_step)
        self.restart_learning()

    def change_end_point(self, value):
        self.end_point += value
        self.end_point = clamp(self.end_point, self.start_point + 1, len(self.measure_data)-1)
        self.usersettings.change_setting_value("end_point", self.end_point)
        self.restart_learning()

    def change_set_tempo(self, value):
        self.set_tempo += 5 * value
        self.set_tempo = clamp(self.set_tempo, 10, 500)
        self.usersettings.change_setting_value("set_tempo", self.set_tempo)

    def change_hand_color(self, value, hand):
        if hand == 'RIGHT':
            self.hand_colorR += value
            self.hand_colorR = clamp(
                self.hand_colorR, 0, len(self.hand_colorList) - 1)
            self.usersettings.change_setting_value(
                "hand_colorR", self.hand_colorR)
        elif hand == 'LEFT':
            self.hand_colorL += value
            self.hand_colorL = clamp(
                self.hand_colorL, 0, len(self.hand_colorList) - 1)
            self.usersettings.change_setting_value(
                "hand_colorL", self.hand_colorL)

    # Get midi song tempo

    def get_tempo(self, mid):
        for msg in mid:  # Search for tempo
            if msg.type == 'set_tempo':
                return msg.tempo
        return 500000  # If not found return default tempo

    def load_song_from_cache(self, song_path):
        # Load song from cache
        try:
            if os.path.isfile('Songs/cache/' + song_path + '.p'):
                print("Loading song from cache")
                with open('Songs/cache/' + song_path + '.p', 'rb') as handle:
                    cache = pickle.load(handle)
                    version = cache['version'] if 'version' in cache else 1
                    self.song_tempo = cache['song_tempo']
                    self.ticks_per_beat = cache['ticks_per_beat']
                    self.song_tracks = cache['song_tracks']
                    self.measure_data = cache['measure_data']
                    self.split_data = cache['split_data']
                    self.loading = 4
                    return version
            else:
                return -1
        except Exception as e:
            print(e)

    def load_midi(self, song_path):
        while self.loading < 4 and self.loading > 0:
            time.sleep(1)

        self.readonly(False)
        touch_file(song_path)
        self.readonly(True)

        if song_path == self.loaded_midi:
            return

        self.loaded_midi = song_path
        self.loading = 1  # 1 = Load..
        self.is_started_midi = False  # Stop current learning song
        self.t = threading.currentThread()

        # Load song from cache
        cache_version = self.load_song_from_cache(song_path)
        if cache_version == CACHE_VERSION:
            self.load_bookmarks(song_path)
            return
        print("Version in cached file :"+str(cache_version)+". Current format is : " + str(CACHE_VERSION) + ". Reload needed.")

        try:
            # Load the midi file
            mid = mido.MidiFile('Songs/' + song_path)

            # Get tempo and Ticks per beat
            self.song_tempo = self.get_tempo(mid)
            self.ticks_per_beat = mid.ticks_per_beat

            # Assign Tracks to different channels before merging to know the message origin
            self.loading = 2  # 2 = Process

            # Merge tracks
            self.loading = 3  # 3 = Merge

            music_splitter = MusicSplitter.create_song_tracks(mid)

            self.split_data = music_splitter.split_data
            self.measure_data = music_splitter.measure_data
            self.song_tracks = music_splitter.midi_messages

            fastColorWipe(self.ledstrip.strip, True, self.ledsettings)
            self.readonly(False)
            # Save to cache
            with open('Songs/cache/' + song_path + '.p', 'wb') as handle:
                cache = {'song_tempo': self.song_tempo, 'ticks_per_beat': self.ticks_per_beat,
                         'song_tracks': self.song_tracks,
                         'measure_data': self.measure_data, 'version': CACHE_VERSION,
                         'split_data': self.split_data}
                pickle.dump(cache, handle, protocol=pickle.HIGHEST_PROTOCOL)

            self.readonly(True)

            self.loading = 4  # 4 = Done
            self.load_bookmarks(song_path)
        except Exception as e:
            print(e)
            traceback.print_exc()
            self.loading = 5  # 5 = Error!
            self.loaded_midi = None

    def show_notes_to_press(self, current_index, notes_to_press):
        for note in notes_to_press:
            note_position = get_note_position(note, self.ledstrip, self.ledsettings, TRASPOSE_LEARNING*self.traspose)
            isWhite = get_key_color(note)

            red = 255
            green = 255
            blue = 255
            if notes_to_press[note][0]["channel"] == 0:
                red = int(self.hand_colorList[self.hand_colorR][0])
                green = int(self.hand_colorList[self.hand_colorR][1])
                blue = int(self.hand_colorList[self.hand_colorR][2])
            if notes_to_press[note][0]["channel"] == 1:
                red = int(self.hand_colorList[self.hand_colorL][0])
                green = int(self.hand_colorList[self.hand_colorL][1])
                blue = int(self.hand_colorList[self.hand_colorL][2])

            count = len(notes_to_press[note])
            rb = 1 if red > 0 else 0
            gb = 1 if green > 0 else 0
            bb = 1 if blue > 0 else 0

            brightness = LOWEST_LED_BRIGHT
            if count > 1:
                brightness = MAX_LED_BRIGHT
            elif isWhite:
                brightness = MIDDLE_LED_BRIGHT
            red = clamp(rb * brightness, 0, 255)
            green = clamp(gb * brightness, 0, 255)
            blue = clamp(bb * brightness, 0, 255)

            self.set_pixel_color(note_position, Color(green, red, blue), None)

        markerColor = Color(LOWEST_LED_BRIGHT, LOWEST_LED_BRIGHT, 0)

        self.ledstrip.strip.show()

    def midi_note_to_notation(self, msg):
        if msg.type == 'note_on' or msg.type == 'note_off':
            notestr = midi_note_num_to_string(msg.note)
            if msg.type == 'note_on' and msg.velocity > 0:
                on_off = "ON"
            else:
                on_off = "OFF"
            offset = ""
            if msg.time > 0:
                offset = "+"+str(msg.time)

            # Construct the notation string
            return f"{notestr} {on_off}  {offset}"
        else:
            return str(msg)

    def set_pixel_color(self, led_idx, color, switch_off_mode):
        if switch_off_mode == "MARKER" or switch_off_mode == "NOTE_OFF":
            self.switch_off_leds[led_idx] = switch_off_mode
        elif switch_off_mode == None:
            self.switch_off_leds.pop(led_idx, None)
        self.ledstrip.strip.setPixelColor(led_idx, color)

    def switch_off_all_leds(self):
        fastColorWipe(self.ledstrip.strip, True, self.ledsettings)
        self.switch_off_leds.clear()

    def switch_off_markers(self):
        remove = []
        for led_idx in self.switch_off_leds:
            if (self.switch_off_leds[led_idx] == "MARKER"):
                self.ledstrip.strip.setPixelColor(led_idx, Color(0, 0, 0))
                remove.append(led_idx)

        if remove:
            self.ledstrip.strip.show()
            for led_idx in remove:
                del self.switch_off_leds[led_idx]

    def process_midi_events(self):
        for msg_in in self.midiports.inport.iter_pending():
            if msg_in.type == 'sysex' and self.blind_mode:
                strmsg = str(msg_in.data)
                if strmsg == '(68, 126, 126, 127, 15, 1, 8, 0, 1, 0, 1, 0, 2, 0)':
                    self.restart_blind = True
            elif msg_in.type in ("note_off", "note_on"):
                note = int(find_between(str(msg_in), "note=", " "))
                note_position = get_note_position(note, self.ledstrip, self.ledsettings, self.traspose)
                if "note_off" in str(msg_in):
                    velocity = 0
                    if note_position in self.switch_off_leds:
                        self.switch_off_leds.pop(note_position, None)
                        self.ledstrip.strip.setPixelColor(note_position, Color(0, 0, 0))
                        self.ledstrip.strip.show()
                else:
                    velocity = int(find_between(str(msg_in), "velocity=", " "))
                self.midi_messages.put({"note": note, "velocity": velocity,
                                        "position": note_position})

    def wait_notes_to_press(self, current_index, start_score, notes_to_press, ignore_first_delay):
        if not notes_to_press:
            return
        if not self.blind_mode:
            self.show_notes_to_press(current_index, notes_to_press)

        start_waiting = time.time()
        start_wrong_keys = self.wrong_keys
        refresh_led_strip = False
        elapsed_already = 0

        while notes_to_press and self.is_started_midi:
            self.process_midi_events()
            if self.restart_blind:
                break
            while not self.midi_messages.empty():
                msg = self.midi_messages.get()

                note_position = msg["position"]
                velocity = msg["velocity"]
                note = msg["note"]
                note -= (1-TRASPOSE_LEARNING) * self.traspose

                if velocity > 0:
                    if note in notes_to_press:
                        if len(notes_to_press[note]) == 1:
                            notes_to_press.pop(note)
                            self.set_pixel_color(note_position, Color(32, 0, 0), "NOTE_OFF")
                            refresh_led_strip = True
                        else:
                            notes_to_press[note].pop(0)
                            if self.blind_mode:
                                self.set_pixel_color(note_position, Color(32, 0, 0), "NOTE_OFF")
                                refresh_led_strip = True
                            else:
                                self.show_notes_to_press(current_index, notes_to_press)

                    else:
                        self.wrong_keys += 1
                        self.set_pixel_color(note_position, Color(0, 32, 0), "NOTE_OFF")
                        if self.wrong_keys > 0:
                            brightness1 = min(self.wrong_keys, 3)
                            brightness2 = max(min(self.wrong_keys-3, 3), 0)
                            led_brightness1 = [0, LOWEST_LED_BRIGHT, MIDDLE_LED_BRIGHT, MAX_LED_BRIGHT][brightness1]
                            led_brightness2 = [0, LOWEST_LED_BRIGHT, MIDDLE_LED_BRIGHT, MAX_LED_BRIGHT][brightness2]
                            self.color_led_strip_borders(Color(0, led_brightness1, 0), 0, 3)
                            self.color_led_strip_borders(Color(0, led_brightness2, 0), 3, 6)
                        if (self.wrong_keys - start_wrong_keys == 16 and self.blind_mode):
                            self.blind_mode = False
                            self.show_notes_to_press(current_index, notes_to_press)
                        else:
                            refresh_led_strip = True
            elapsed_already = max(0, time.time()-start_waiting - 0.25)
            if ignore_first_delay:
                elapsed_already = 0
            if elapsed_already > 1:
                elapsed_already = 1
            if self.practice == PRACTICE_ARCADE:
                self.current_score = start_score - (self.wrong_keys * 10 + self.total_wait_time + elapsed_already)
                if self.current_score <= 0:
                    # print("Score reached zero")
                    notes_to_press.clear()
                    self.total_wait_time = 10000
                    break
            elif self.practice == PRACTICE_PERFECTION:
                self.current_score = (self.total_wait_time + elapsed_already) * 3 + self.wrong_keys * 10
                if self.wrong_keys - start_wrong_keys > 15:
                    self.blind_mode = False
            if refresh_led_strip:
                self.ledstrip.strip.show()
                refresh_led_strip = False
            if self.listen_again:
                self.listen_measures()
                if not self.blind_mode:
                    self.show_notes_to_press(current_index, notes_to_press)
                    self.ledstrip.strip.show()
                else:
                    self.switch_off_all_leds()
                self.listen_again = False

        self.switch_off_markers()
        if self.hands != 0:
            self.switch_off_all_leds()

        self.total_wait_time += elapsed_already

    def is_pedal_command(self, msg):
        return msg.type == 'control_change' and msg.control == 64

    def dump_note(self, note_idx):
        msg = self.song_tracks[note_idx]
        if DEBUG:
            print("      note ["+str(msg.channel)+"] : "+str(note_idx)+"@"+format(
                self.song_tracks[note_idx].time, '.2f')+"  " + self.midi_note_to_notation(msg))

    def modify_brightness(self, color, new_brightness):
        green, red, blue = getRGB(color)
        rb = 1 if red > 0 else 0
        gb = 1 if green > 0 else 0
        bb = 1 if blue > 0 else 0
        return Color(gb * new_brightness, rb * new_brightness, bb * new_brightness)

    def color_led_strip_borders(self, color, start, end):
        lowest = get_note_position(21, self.ledstrip, self.ledsettings, TRASPOSE_LEARNING*self.traspose)
        highest = get_note_position(108, self.ledstrip, self.ledsettings, TRASPOSE_LEARNING*self.traspose)
        for i in range(start, end):
            self.ledstrip.strip.setPixelColor(lowest - 3 - i, color)
            self.ledstrip.strip.setPixelColor(highest + 3 + i, color)

    def listen_measures(self, start=None, end=None):
        if start is None or end is None:
            start = self.last_heard_range[0]
            end = self.last_heard_range[1]
        self.last_heard_range = [start, end]
        try:
            self.switch_off_all_leds()
            time_prev = time.time()

            end_idx = self.measure_data[end]['note_index']

            start_idx = self.measure_data[start]['note_index']

            msg_index = start_idx
            self.current_measure = start

            for msg_and_time in self.song_tracks[start_idx:end_idx]:
                msg = msg_and_time.msg

                # Exit thread if learning is stopped
                if not self.is_started_midi:
                    break

                # Get time delay
                tDelay = mido.tick2second(msg.time, self.ticks_per_beat, self.song_tempo * 100 / self.set_tempo)

                # Realize time delay, consider also the time lost during computation
                delay = tDelay - (time.time() - time_prev) - 0.003  # 0.003 sec calibratable to acount for extra time loss
                if msg_index > start_idx and msg_and_time.time > self.song_tracks[msg_index-1].time:
                    self.ledstrip.strip.show()
                    delay = delay - 0.05
                if delay > 0:
                    time.sleep(delay)
                time_prev = time.time()
                while (self.current_measure+1 < len(self.measure_data) and
                       self.measure_data[self.current_measure+1]['note_index'] <= msg_index):
                    self.current_measure += 1

                # Light-up LEDs with the notes to press
                if not msg.is_meta:
                    # Calculate note position on the strip and display
                    if msg.type == 'note_on' or msg.type == 'note_off':
                        note_position = get_note_position(
                            msg.note, self.ledstrip, self.ledsettings, TRASPOSE_LEARNING*self.traspose)
                        isWhite = get_key_color(msg.note)
                        if msg.velocity == 0 or msg.type == 'note_off':
                            red = 0
                            green = 0
                            blue = 0
                        elif msg.channel == 0:
                            red = int(self.hand_colorList[self.hand_colorR][0])
                            green = int(self.hand_colorList[self.hand_colorR][1])
                            blue = int(self.hand_colorList[self.hand_colorR][2])
                        elif msg.channel == 1:
                            red = int(self.hand_colorList[self.hand_colorL][0])
                            green = int(self.hand_colorList[self.hand_colorL][1])
                            blue = int(self.hand_colorList[self.hand_colorL][2])
                        else:
                            red = 0
                            green = 0
                            blue = 0

                        brightness = MIDDLE_LED_BRIGHT if isWhite else LOWEST_LED_BRIGHT

                        self.ledstrip.strip.setPixelColor(
                            note_position, self.modify_brightness(Color(green, red, blue), brightness))

                    # Play selected Track
                    if not self.is_pedal_command(msg):
                        if hasattr(msg, "note"):
                            msg = deepcopy(msg)
                            msg.note += (1-TRASPOSE_LEARNING) * self.traspose
                        self.midiports.playport.send(msg)
                msg_index += 1
            self.ledstrip.strip.show()
            if self.hands == 0:
                time.sleep(0.5)
                # stop all notes
                for channel in range(16):
                    self.midiports.playport.send(mido.Message('control_change', channel=channel, control=123, value=0))

        except Exception as e:
            print(e)
            traceback.print_exc()
            self.is_started_midi = False

    def get_measures_per_exercise(self):
        return int(self.learnStepList[self.learn_step].split("/")[0])

    def get_repetitions(self):
        repetitions = self.learnStepList[self.learn_step].split("/")[1]
        return 1000000 if repetitions == '∞' else int(repetitions)

    def learn_midi(self):
        self.prev_score = None
        self.prev_wrong = None
        self.switch_off_leds = {}
        self.blind_mode = False
        self.repetition_count = 0
        # Preliminary checks
        if self.is_started_midi:
            return
        if self.loading == 0:
            self.menu.render_message("Load song to start", "", 1500)
            return
        elif self.loading > 0 and self.loading < 4:
            self.is_started_midi = True  # Prevent restarting the Thread
            while self.loading > 0 and self.loading < 4:
                time.sleep(0.1)
        if self.loading == 4:
            self.is_started_midi = True  # Prevent restarting the Thread
        elif self.loading == 5:
            self.is_started_midi = False  # Allow restarting the Thread
            return

        self.t = threading.currentThread()
        keep_looping = True

        start_measure = int(self.start_point - 1)
        start_measure = clamp(start_measure, 0, len(self.measure_data)-1)
        end_measure = int(self.end_point)
        end_measure = clamp(end_measure, start_measure,
                            len(self.measure_data)-1)

        if self.practice in (PRACTICE_PERFECTION, PRACTICE_PROGRESSIVE):
            end_measure = clamp(start_measure + self.get_measures_per_exercise(),
                                start_measure, len(self.measure_data)-1)

        while "note_index" not in self.measure_data[end_measure] and end_measure >= start_measure:
            end_measure -= 1

        last_played_measure = -1

        while (keep_looping):
            self.learning_midi = True
            ignore_first_delay = True
            if self.practice in (PRACTICE_MELODY, PRACTICE_ARCADE, PRACTICE_PERFECTION) and not self.blind_mode:
                red1 = int(self.hand_colorList[self.hand_colorR][0])
                green1 = int(self.hand_colorList[self.hand_colorR][1])
                blue1 = int(self.hand_colorList[self.hand_colorR][2])
                red2 = int(self.hand_colorList[self.hand_colorL][0])
                green2 = int(self.hand_colorList[self.hand_colorL][1])
                blue2 = int(self.hand_colorList[self.hand_colorL][2])

                pattern = []
                pattern.append(self.modify_brightness(
                    Color(green1, red1, blue1), LOWEST_LED_BRIGHT))
                pattern.append(self.modify_brightness(
                    Color(green2, red2, blue2), LOWEST_LED_BRIGHT))
                setLedPattern(self.ledstrip.strip, pattern)
            elif self.practice == PRACTICE_PROGRESSIVE or self.blind_mode:
                pattern = []
                if (self.get_repetitions() < 10):
                    if self.repetition_count == 0:
                        pattern.append(Color(LOWEST_LED_BRIGHT, LOWEST_LED_BRIGHT, LOWEST_LED_BRIGHT))
                        for i in range(self.get_repetitions() - 1):
                            pattern.append(Color(0, 0, 0))
                    else:
                        ignore_first_delay = False
                        for i in range(self.get_repetitions()):
                            if self.repetition_count > i:
                                pattern.append(Color(LOWEST_LED_BRIGHT, 0, 0))
                            else:
                                pattern.append(Color(0, 0, 0))
                else:
                    pattern.append(Color(LOWEST_LED_BRIGHT, 0, 0))
                pattern.append(Color(0, 0, 0))
                setLedPattern(self.ledstrip.strip, pattern)
            else:
                changeAllLedsColor(
                    self.ledstrip.strip, LOWEST_LED_BRIGHT, LOWEST_LED_BRIGHT, MIDDLE_LED_BRIGHT)

            time.sleep(0.25)
            if self.practice in (PRACTICE_PERFECTION, PRACTICE_PROGRESSIVE, PRACTICE_LISTEN) and last_played_measure != start_measure:
                last_played_measure = start_measure
                self.listen_measures(start_measure, end_measure)
            if self.practice == PRACTICE_LISTEN:
                keep_looping = False
                self.learning_midi = False
                break

            try:
                self.switch_off_all_leds()
                time_prev = time.time()
                notes_to_press = {}

                end_idx = self.measure_data[end_measure]['note_index']
                start_idx = self.measure_data[start_measure]['note_index']
                self.current_measure = start_measure - 1

                self.total_wait_time = 0.0
                self.wrong_keys = 0
                start_score = 100
                self.current_score = start_score

                accDelay = 0

                if not self.blind_mode or self.repetition_count == 0:
                    # Flush pending notes
                    self.process_midi_events()
                    self.midi_messages.queue.clear()

                if self.practice in (PRACTICE_MELODY, PRACTICE_ARCADE, PRACTICE_PROGRESSIVE, PRACTICE_PERFECTION):
                    self.color_led_strip_borders(Color(MIDDLE_LED_BRIGHT, 0, 0), 0, 6)

                self.restart_blind = False
                msg_index = start_idx - 1
                for msg_and_time in self.song_tracks[start_idx:end_idx]:
                    msg = msg_and_time.msg
                    msg_index += 1
                    # Exit thread if learning is stopped
                    if not self.is_started_midi:
                        break

                    # Get time delay
                    tDelay = mido.tick2second(msg.time, self.ticks_per_beat, self.song_tempo * 100 / self.set_tempo)

                    accDelay += tDelay

                    while (self.current_measure+1 < len(self.measure_data) and
                           self.measure_data[self.current_measure+1]['note_index'] <= msg_index):
                        self.current_measure += 1
                        if DEBUG:
                            print("--------------   Measure " +
                                  str(self.current_measure))

                    if self.practice == PRACTICE_ARCADE:
                        self.current_score = start_score - (self.wrong_keys * 10 + self.total_wait_time)
                        if self.current_score < 0:
                            break
                    elif self.practice in (PRACTICE_PERFECTION, PRACTICE_PROGRESSIVE):
                        self.current_score = self.total_wait_time * 3 + self.wrong_keys * 10
                        if self.restart_blind:
                            break

                    # Light-up LEDs with the notes to press
                    if not msg.is_meta:
                        # Calculate note position on the strip and display
                        if ((msg.type == 'note_on' or msg.type == 'note_off') and msg.velocity > 0 and
                                not self.blind_mode):
                            note_position = get_note_position(
                                msg.note, self.ledstrip, self.ledsettings, TRASPOSE_LEARNING*self.traspose)
                            if msg.velocity == 0 or msg.type == 'note_off':
                                red = 0
                                green = 0
                                blue = 0
                            elif msg.channel == 0 and self.hands == 1:
                                red = int(self.hand_colorList[self.hand_colorR][0])
                                green = int(self.hand_colorList[self.hand_colorR][1])
                                blue = int(self.hand_colorList[self.hand_colorR][2])
                            elif msg.channel == 1 and self.hands == 2:
                                red = int(self.hand_colorList[self.hand_colorL][0])
                                green = int(self.hand_colorList[self.hand_colorL][1])
                                blue = int(self.hand_colorList[self.hand_colorL][2])
                            elif msg.channel in (1, 2) and self.hands == 0:
                                red = 16
                                green = 16
                                blue = 16
                            else:
                                red = 0
                                green = 0
                                blue = 0
                            isWhite = get_key_color(msg.note)
                            brightness = MIDDLE_LED_BRIGHT if isWhite else LOWEST_LED_BRIGHT

                            self.ledstrip.strip.setPixelColor(
                                note_position, self.modify_brightness(Color(green, red, blue), brightness))

                            # skip show, if there are note_on events
                            if not still_notes_in_chord(self.song_tracks, msg_index):
                                self.ledstrip.strip.show()

                        # Save notes to press
                        if msg.type == 'note_on' and msg.velocity > 0 and (
                                self.hands == 0 or msg.channel == self.hands-1):
                            if not notes_to_press:
                                accDelay = 0    # start calculating from now how much time we accumulated

                            if msg.note not in notes_to_press:
                                notes_to_press[msg.note] = [
                                    {"idx": msg_index, "channel": msg.channel}]
                            else:
                                notes_to_press[msg.note].append(
                                    {"idx": msg_index, "channel": msg.channel})

                        # Play selected Track
                        if (
                                (self.hands == 1 and self.mute_hand != 2 and msg.channel == 1) or
                                # send midi sound for Left hand
                                (self.hands == 2 and self.mute_hand != 1 and msg.channel == 0)
                                # send midi sound for Right hand
                        ):
                            if msg.type in ['note_on', 'note_off']:
                                # Create a new message with the same type, note, and channel, but with max velocity (127)
                                new_msg = msg.copy(velocity=127)
                                self.midiports.playport.send(new_msg)
                            else:
                                # For other types of messages, just forward them as they are
                                self.midiports.playport.send(msg)

                    # Realize time delay, consider also the time lost during computation
                    # 0.003 sec calibratable to acount for extra time loss
                    delay = max(0, tDelay - (time.time() - time_prev) - 10.003)
                    wait_until = time.time() + delay
                    while time.time() < wait_until:
                        self.process_midi_events()
                        to_sleep = min(0.02, wait_until-time.time())
                        if to_sleep > 0:
                            time.sleep(to_sleep)
                    time_prev = time.time()

                    # Check notes to press
                    if not msg.is_meta:
                        try:
                            self.socket_send.append(self.song_tracks[msg_index].time)
                        except Exception as e:
                            print(e)

                        self.dump_note(msg_index)

                        if (msg_index in self.split_data
                            and msg.type in ['note_on', 'note_off']
                            and notes_to_press
                                and self.practice in (PRACTICE_MELODY, PRACTICE_ARCADE, PRACTICE_PROGRESSIVE, PRACTICE_PERFECTION)):
                            self.wait_notes_to_press(msg_index,
                                                     start_score, notes_to_press, ignore_first_delay)
                            ignore_first_delay = False
                            accDelay = 0

                        # Switch off LEDs with the notes to press
                        if self.practice not in (PRACTICE_MELODY, PRACTICE_ARCADE, PRACTICE_PROGRESSIVE, PRACTICE_PERFECTION):
                            # Calculate note position on the strip and display
                            if ((hasattr(msg, "velocity") and msg.velocity == 0) and not self.blind_mode):
                                note_position = get_note_position(
                                    msg.note, self.ledstrip, self.ledsettings, TRASPOSE_LEARNING*self.traspose)
                                self.set_pixel_color(note_position, Color(0, 0, 0), None)
                                # self.ledstrip.strip.show()

                if self.practice in (PRACTICE_MELODY, PRACTICE_ARCADE, PRACTICE_PROGRESSIVE, PRACTICE_PERFECTION):
                    self.wait_notes_to_press(msg_index,
                                             start_score, notes_to_press, ignore_first_delay)

            except Exception as e:
                print(e)
                traceback.print_exc()
                self.is_started_midi = False
            if self.is_started_midi:
                if not self.blind_mode and self.get_repetitions() < 10:
                    if self.practice == PRACTICE_ARCADE and self.current_score < 0:
                        changeAllLedsColor(self.ledstrip.strip, 0, 16, 0)
                    elif self.practice == PRACTICE_PERFECTION and (self.current_score >= 10 or self.restart_blind):
                        changeAllLedsColor(self.ledstrip.strip, 0, 16, 0)
                    else:
                        changeAllLedsColor(self.ledstrip.strip, 16, 0, 0)

                if self.get_repetitions() < 10 or self.practice not in (PRACTICE_MELODY, PRACTICE_ARCADE, PRACTICE_PROGRESSIVE, PRACTICE_PERFECTION):
                    if self.practice == PRACTICE_PERFECTION:
                        if self.current_score < 10 and not self.restart_blind:
                            if self.blind_mode:
                                self.repetition_count += 1
                                if self.repetition_count == self.get_repetitions():
                                    start_measure += 1
                                    self.blind_mode = False
                                    changeAllLedsColor(
                                        self.ledstrip.strip, 16, 0, 0)
                                    time.sleep(0.5)
                            else:
                                self.blind_mode = True
                                self.repetition_count = 0
                                time.sleep(0.5)
                        if self.restart_blind or (self.current_score >= 10 and self.blind_mode):
                            changeAllLedsColor(self.ledstrip.strip, 0, 16, 0)
                            self.repetition_count = 0
                            time.sleep(0.5)
                        if not self.restart_blind:
                            self.prev_score = self.current_score
                            self.prev_wrong = self.wrong_keys
                    else:
                        if self.practice == PRACTICE_PROGRESSIVE:
                            if self.wrong_keys == 0:
                                self.repetition_count += 1
                                if self.repetition_count == self.get_repetitions():
                                    start_measure += 1
                                    self.repetition_count = 0
                                changeAllLedsColor(self.ledstrip.strip, 16, 0, 0)
                            else:
                                changeAllLedsColor(self.ledstrip.strip, 0, 16, 0)
                        if self.practice in (PRACTICE_MELODY, PRACTICE_ARCADE, PRACTICE_PROGRESSIVE):
                            time.sleep(0.5)
                end_measure = clamp(
                    start_measure + self.get_measures_per_exercise(), start_measure, len(self.measure_data)-1)

            self.switch_off_all_leds()
            # stop all notes
            for channel in range(16):
                # switch off note
                self.midiports.playport.send(mido.Message('control_change', channel=channel, control=123, value=0))
                # release pedal
                self.midiports.playport.send(mido.Message('control_change', channel=channel, control=64, value=0))

            self.learning_midi = False
            if (not self.is_loop_active or self.is_started_midi == False or start_measure >= len(self.measure_data)):
                keep_looping = False

    def convert_midi_to_abc(self, midi_file):
        if not os.path.isfile('Songs/' + midi_file.replace(".mid", ".abc")):
            # subprocess.call(['midi2abc',  'Songs/' + midi_file, '-o', 'Songs/' + midi_file.replace(".mid", ".abc")])
            self.readonly(False)
            try:
                subprocess.check_output(
                    ['midi2abc',  'Songs/' + midi_file, '-o', 'Songs/' + midi_file.replace(".mid", ".abc")])
            except Exception as e:
                # check if e contains the string 'No such file or directory'
                if 'No such file or directory' in str(e):
                    print("Midiabc not found, installing...")
                    self.install_midi2abc()
                    self.convert_midi_to_abc(midi_file)
            self.readonly(True)
        else:
            print("file already converted")

    def readonly(self, enable):
        if self.is_read_only_fs:
            set_read_only(enable)

    def install_midi2abc(self):
        print("Installing abcmidi")
        subprocess.call(['sudo', 'apt-get', 'install', 'abcmidi', '-y'])

    def load_bookmarks(self, song_path):
        self.end_point = clamp(self.end_point, 1, len(self.measure_data))
        self.start_point = clamp(self.start_point, 1, self.end_point)
        try:
            self.bookmark_filename = 'Songs/cache/' + song_path + '.bookmarks'
            self.bookmarks = set()
            if os.path.isfile(self.bookmark_filename):
                with open(self.bookmark_filename, 'rb') as handle:
                    self.bookmarks = set(pickle.load(handle))
        except Exception as e:
            print(e)
        self.menu.update_bookmarks()
        self.menu.show()

    def toggle_bookmark(self):
        if self.start_point in self.bookmarks:
            self.bookmarks.remove(self.start_point)
        else:
            self.bookmarks.add(self.start_point)

        if hasattr(self, "bookmark_filename"):
            self.readonly(False)
            with open(self.bookmark_filename, 'wb') as handle:
                cache = {'song_tempo': self.song_tempo, 'ticks_per_beat': self.ticks_per_beat,
                         'song_tracks': self.song_tracks,
                         'measure_data': self.measure_data,
                         'split_data': self.split_data}
                pickle.dump(self.bookmarks, handle, protocol=pickle.HIGHEST_PROTOCOL)
            self.readonly(True)

    def get_bookmarks(self):
        return sorted(self.bookmarks)
