# from lib.functions import midi_note_num_to_string
import mido
from mido import MidiFile


# def midi_note_num_to_string(note_midi_idx):
#    # Calculate the octave and note number
#    octave = (note_midi_idx // 12) - 1
#    note_num = note_midi_idx % 12
#    # Map the note number to a note letter and accidental
#    notes = {0: 'C', 1: 'C#', 2: 'D', 3: 'Eb', 4: 'E', 5: 'F',
#             6: 'F#', 7: 'G', 8: 'G#', 9: 'A', 10: 'Bb', 11: 'B'}
#    return f"{notes[note_num]}{octave}"


# notes within this distance are considered part of same chord
THRESHOLD_CHORD_NOTE_DISTANCE = 0.05
DEBUG_MARKERS = False


class MidiMessageWithTime:
    time: int

    def __init__(self, msg, time: int):
        self.msg = msg
        self.time = time


class MusicSplitter:

    _gaps_array: list[dict[str, dict[int, float]]]

    def __init__(self, midi_messages: list[MidiMessageWithTime]):
        self.midi_messages = midi_messages

    def calculate_measure_and_split_data(self, ticks_per_beat, max_length):
        self.measure_data = self.calculate_measure_data(ticks_per_beat)
        self._gaps_array = MusicSplitter._calculate_note_gaps(self.midi_messages)
        self.split_data = self.do_split(ticks_per_beat, max_length)

    def find_note_with_same_time(self, notes_to_press, idx):
        channel = self.midi_messages[idx].msg.channel
        for note in notes_to_press:
            for i in range(len(notes_to_press[note])):
                note_index = notes_to_press[note][i]["idx"]
                # ipdb.set_trace()
                if idx != note_index and notes_to_press[note][i]["channel"] == channel and abs(self.midi_messages[note_index].time - self.midi_messages[idx].time) < THRESHOLD_CHORD_NOTE_DISTANCE:
                    return self.midi_messages[note_index].msg
        return None

    def get_next_chord(self, index, channel=None):
        time_next_chord = None
        notes = []
        for i in range(index + 1, index + 50):
            if i >= len(self.midi_messages):
                break
            if time_next_chord is not None and self.midi_messages[i].time - time_next_chord > THRESHOLD_CHORD_NOTE_DISTANCE:
                break
            if self.midi_messages[i].msg.type == "note_on" and (channel is None or self.midi_messages[i].msg.channel == channel) and self.midi_messages[i].msg.velocity > 0:
                if time_next_chord is None:
                    time_next_chord = self.midi_messages[i].time
                notes.append(i)
        return notes

    def get_highest_chord_note_in_channel(self, channel, index):
        indices = self.get_next_chord(index, channel)
        notes = [self.midi_messages[i].note for i in indices]
        return max(notes) if notes else None

    def get_lowest_chord_note_in_channel(self, channel, index):
        indices = self.get_next_chord(index, channel)
        notes = [self.midi_messages[i].note for i in indices]
        return min(notes) if notes else None

    def do_split(self, ticks_per_beat, max_length):
        accDelay = 0
        tDelay = 0
        msg_index = 0
        collected_notes = {}
        accumulated_chord = None
        split_data: dict[int, bool] = {}
        release_note_count = 0
        last_press_note_time = -11

        measure_length = 100
        currTime = 0
        note_off_found = False
        for msg in self.midi_messages:

            if msg.msg.is_meta and msg.msg.type == 'time_signature':
                time_signature = float(msg.msg.numerator/msg.msg.denominator)
                measure_length = int(4 * time_signature * ticks_per_beat)

            tDelay = msg.time / measure_length
            accDelay += tDelay
            currTime += tDelay

            if tDelay > 0.05:
                release_note_count = 0

            accDelay += tDelay

            if not msg.msg.is_meta:
                # Save notes to press
                if msg.msg.type == 'note_on' and msg.msg.velocity > 0:
                    last_press_note_time = currTime
                    if not collected_notes:
                        accDelay = 0    # start calculating from now how much time we accumulated
                        note_off_found = False
                    if msg.msg.note not in collected_notes:
                        collected_notes[msg.msg.note] = [
                            {"idx": msg_index, "channel": msg.msg.channel}]
                    else:
                        collected_notes[msg.msg.note].append(
                            {"idx": msg_index, "channel": msg.msg.channel})
                    if self.find_note_with_same_time(collected_notes, msg_index) and accumulated_chord is None:
                        accumulated_chord = currTime
                if msg.msg.type == "note_off" and collected_notes:
                    note_off_found = True

                if msg.msg.channel in (0, 1):
                    current_hand = msg.msg.channel
                    other_hand = 1 - msg.msg.channel

                    gaps = self._gaps_array[msg_index]
                    split_point_found = False
                    msg_is_note_on_off = msg.msg.type in ['note_on', 'note_off']
                    if accDelay >= max_length-0.01:
                        split_point_found = True
                    elif ((gaps['time_to_next'][current_hand] is None or gaps['time_to_next'][current_hand] > 0.12)
                          and (gaps['time_to_next'][other_hand] is None
                               or (gaps['time_to_next'][other_hand] > 0.05 and gaps['time_to_next'][other_hand] + gaps['time_to_prev'][other_hand] > 0.12))
                          ):
                        split_point_found = True
                    elif (accumulated_chord is not None and accumulated_chord < currTime
                          and (gaps['time_to_next'][0] is None or gaps['time_to_next'][0] > 0.02)
                          and (gaps['time_to_next'][1] is None or gaps['time_to_next'][1] > 0.02)):
                        chord0 = self.get_next_chord(msg_index, 0)
                        chord1 = self.get_next_chord(msg_index, 1)
                        if not chord0:
                            first_chord = chord1
                        elif not chord1:
                            first_chord = chord0
                        else:
                            first_chord = chord0 if self.midi_messages[chord0[0]
                                                                       ].time < self.midi_messages[chord1[0]].time else chord1
                        if first_chord is not None and len(first_chord) > 1:
                            split_point_found = True

                    if msg_is_note_on_off and msg.msg.velocity == 0:
                        release_note_count += 1
                        if release_note_count > 1:
                            split_point_found = True

                    # there are keys to press
                    # last key pressed longer than 0.1 ago
                    if (split_point_found
                            and msg_is_note_on_off
                            and collected_notes
                            and (
                                (last_press_note_time < currTime - 0.05 and (
                                    accumulated_chord is None
                                    or accumulated_chord < currTime - 0.05
                                    or not still_notes_in_chord(self.midi_messages, msg_index))
                                 ))
                        or note_off_found
                        ):
                        split_data[msg_index] = True
                        collected_notes.clear()
                        accumulated_chord = None
                        note_off_found = False
                        accDelay = 0

            msg_index += 1
        return split_data

    def calculate_measure_data(self, ticks_per_beat):
        measure_data = []
        time_signature = 1
        current_ticks = 0
        current_ticks_in_measure = 0

        tweak_measure_offset = 0
        measure_start = 0
        measure_length = None

        # 1. Calculate in which tick measures start taking MeasureOffset tweak into account
        for i, midi_message in enumerate(self.midi_messages):
            msg = midi_message.msg
            if hasattr(msg, "time"):
                current_ticks += msg.time
                current_ticks_in_measure += msg.time

            if msg.is_meta and msg.type == "text" and msg.text.startswith("MeasureOffset="):
                tweak_measure_offset = int(msg.text[len("MeasureOffset="):])

            if msg.is_meta and msg.type == 'time_signature':
                time_signature = float(msg.numerator/msg.denominator)
                measure_length = int(4 * time_signature * ticks_per_beat)
                measure_data.append(
                    {'start': current_ticks + tweak_measure_offset})
                current_ticks_in_measure = 0
                measure_start = current_ticks

            if measure_length is not None:
                while current_ticks_in_measure > measure_length:
                    current_ticks_in_measure -= measure_length
                    measure_start += measure_length
                    measure_data.append(
                        {'start': measure_start + tweak_measure_offset})
        if measure_length is not None:
            measure_data.append({'start': measure_length + measure_start + tweak_measure_offset})
        else:
            measure_data.append({'start': int(4 * time_signature * ticks_per_beat) + measure_start + tweak_measure_offset})

        # 2. Calculate in which note measures start. Snap to measure is taken into account here
        tweak_snap_to_measure = 5
        measure_pointer = 1
        current_ticks = 0
        measure_data[0]['note_index'] = 0

        for i, midi_message in enumerate(self.midi_messages):
            msg = midi_message.msg
            if hasattr(msg, "time"):
                current_ticks += msg.time
            if msg.is_meta and msg.type == "text" and msg.text.startswith("SnapToMeasure="):
                tweak_snap_to_measure = int(msg.text[len("SnapToMeasure="):])

            if msg.type == "note_on" and msg.velocity > 0:   # snap
                while (measure_pointer < len(measure_data)
                        and current_ticks >= measure_data[measure_pointer]["start"] - tweak_snap_to_measure):
                    measure_data[measure_pointer]['note_index'] = i
                    measure_pointer += 1
        measure_data[len(measure_data)-1]['note_index'] = len(self.midi_messages)
        return measure_data

    @staticmethod
    def _calculate_note_gaps(midi_messages: list[MidiMessageWithTime]):
        # fill prev and next time gaps
        prev_note_on = {}
        curr_prev_note_on = {i: -1 for i in range(2)}

        for i, msg in enumerate(midi_messages):
            prev_note_on[i] = curr_prev_note_on.copy()
            if msg.msg.type == 'note_on':
                channel = msg.msg.channel
                if msg.msg.velocity > 0:
                    curr_prev_note_on[channel] = i

        next_note_on = {}
        curr_next_note_on = {i: -1 for i in range(2)}
        for i in range(len(midi_messages)-1, -1, -1):
            msg = midi_messages[i]
            next_note_on[i] = curr_next_note_on.copy()
            if msg.msg.type == 'note_on':
                channel = msg.msg.channel
                if msg.msg.velocity > 0:
                    curr_next_note_on[channel] = i

        gaps_array: list[dict[str, dict[int, float]]] = [
            {
                'time_to_prev': {i: float('inf') for i in range(2)},
                'time_to_next': {i: float('inf') for i in range(2)}
            } for i in range(len(midi_messages))
        ]

        for i, msg in enumerate(midi_messages):
            if i in prev_note_on:
                if i not in next_note_on:
                    raise Exception("SANITY CHECK ERROR _ test")
                for c in prev_note_on[i]:
                    if prev_note_on[i][c] is not None:
                        gaps_array[i]['time_to_prev'][c] = midi_messages[i].time - \
                            midi_messages[prev_note_on[i][c]].time
                    else:
                        gaps_array[i]['time_to_prev'][c] = float('inf')
                    if next_note_on[i][c] is not None:
                        gaps_array[i]['time_to_next'][c] = midi_messages[next_note_on[i]
                                                                         [c]].time - midi_messages[i].time
                    else:
                        gaps_array[i]['time_to_next'][c] = float('inf')
        return gaps_array

    @staticmethod
    def _separate_hands(mid: MidiFile):
        for k in range(len(mid.tracks)):
            for msg in mid.tracks[k]:
                if not msg.is_meta:
                    if len(mid.tracks) == 2:
                        msg.channel = k
                    else:
                        if msg.channel in (0, 1, 2, 3, 4, 5):
                            msg.channel = msg.channel % 2
                        if mid.tracks[k].name == 'LH':
                            msg.channel = 0
                        if mid.tracks[k].name == 'RH':
                            msg.channel = 1
                    if msg.type == 'note_off':
                        msg.velocity = 0

    @staticmethod
    def get_key(msg):
        return msg.note+msg.channel*1024

    @staticmethod
    def get_note_part(key):
        return key & 1023

    @staticmethod
    def create_song_tracks(mid: MidiFile):
        MusicSplitter._separate_hands(mid)
        time_passed = 0
        chord_notes_on = set()
        unfiltered_song_tracks = mido.merge_tracks(mid.tracks)
        unfiltered_midi_data: list[MidiMessageWithTime] = []
        note_states_with_channel: dict[int, bool] = {}  # Tracks the on/off state of notes
        note_states: dict[int, bool] = {}  # Tracks the on/off state of notes

        for msg in unfiltered_song_tracks:
            ignore_note = False
            if hasattr(msg, 'time'):
                time_passed += msg.time
                if msg.time > 0:
                    chord_notes_on.clear()
            if not msg.is_meta and hasattr(msg, 'note'):
                note_channel = MusicSplitter.get_key(msg)
                if msg.type == 'note_on' and msg.velocity > 0:
                    if msg.note in chord_notes_on:
                        ignore_note = True
                    if msg.note in note_states and note_states[msg.note]:
                        # Insert a note_off event before the new note_on
                        note_off_msg = mido.Message('note_off', note=msg.note, velocity=0, time=0)
                        unfiltered_midi_data.append(MidiMessageWithTime(note_off_msg, time_passed))
                        # Mark the note as off before turning it on again
                        note_states[msg.note] = False
                        # set state off for all notes regardless of channel
                        for key in note_states_with_channel:
                            if MusicSplitter.get_note_part(key) == msg.note:
                                note_states_with_channel[key] = False
                    chord_notes_on.add(msg.note)
                    note_states[msg.note] = True
                    note_states_with_channel[note_channel] = True
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    if note_channel in note_states_with_channel and note_states_with_channel[note_channel]:
                        note_states_with_channel[note_channel] = False
                        note_states[msg.note] = False
                    else:
                        ignore_note = True
            if not ignore_note:
                unfiltered_midi_data.append(MidiMessageWithTime(msg, time_passed))

        song_tracks: list[MidiMessageWithTime] = []

        time_passed = 0
        collected_events_increment_time = 0
        collected_events: set[MidiMessageWithTime] = set()
        for msg in unfiltered_midi_data:
            if time_passed != msg.time:
                events_to_add: list[MidiMessageWithTime] = []
                for event in collected_events:
                    if event.msg.type == 'note_off':
                        events_to_add.append(event)
                for event in collected_events:
                    if event.msg.type != 'note_off':
                        events_to_add.append(event)
                first = True
                increment_time = msg.time - time_passed
                for event in events_to_add:
                    if first:
                        first = False
                        time_passed = msg.time
                        event.msg.time = collected_events_increment_time
                    else:
                        event.msg.time = 0
                    song_tracks.append(event)
                collected_events.clear()
                collected_events_increment_time = increment_time
            collected_events.add(msg)

        music_splitter = MusicSplitter(song_tracks)
        ticks_per_beat = mid.ticks_per_beat

        music_splitter.calculate_measure_and_split_data(ticks_per_beat, 0.125)

        return music_splitter


def still_notes_in_chord(midi_messages: list[MidiMessageWithTime], start_idx):
    for idx in range(start_idx + 1, start_idx + 100):
        if idx >= len(midi_messages):
            return False
        msg = midi_messages[idx].msg
        if hasattr(msg, "time") and msg.time > 0:
            return False
        if msg.type in ('note_on', 'note_off') and msg.velocity > 0:
            return True
    return False


def get_tempo(mid):
    for msg in mid:  # Search for tempo
        if msg.type == 'set_tempo':
            return msg.tempo
    return 500000  # If not found return default tempo


def sort_midi_events(event: MidiMessageWithTime):
    event_priority = 0 if event.msg.type == 'note_off' or (event.msg.type == 'note_on' and event.msg.velocity == 0) else 1
    return (event.time, event_priority)


def test():
    # mid = mido.MidiFile('s:\\media\\mp3\\classical\\gershwin\\piano\\midi\\swanee.mid')
    mid = mido.MidiFile('s:\\media\\mp3\\classical\\gershwin\\piano\\midi\\the man I love.mid')
    # mid = mido.MidiFile('E:\\sweet-and-low.mid')
    # mid = mido.MidiFile('E:\\backup_piano\\piano_backup_24\\Piano-LED-Visualizer\\Songs\\Albeniz - Granada.mid')

    # Get tempo and Ticks per beat
    ticks_per_beat = mid.ticks_per_beat

    music_splitter = MusicSplitter.create_song_tracks(mid)
    measure_data = music_splitter.measure_data

    active_notes = {}
    # Loop through each midi event and its corresponding time
    accDelay = 0
    body = ""
    width_roll = 0
    ZOOM = 120
    message_index = -1
    color_class = ["red", "green", "yellow", "blue"]
    color_idx = 0
    current_measure = -1
    for midi_event_and_time in music_splitter.midi_messages:
        midi_event = midi_event_and_time.msg
        message_index += 1

        while (current_measure+1 < len(measure_data) and
                measure_data[current_measure+1]['note_index'] <= message_index):
            current_measure += 1
            body += f'<div class="measure" style="left: {(measure_data[current_measure]["start"] /ticks_per_beat) *ZOOM}px;"></div>'
            body += f'<div class="measure_number" style="left: {(measure_data[current_measure]["start"] /ticks_per_beat) *ZOOM}px;">{current_measure+1}</div>'

        if not midi_event.is_meta:
            tDelay = midi_event.time / ticks_per_beat
            accDelay += tDelay
            note_type = midi_event.type

            if note_type == 'note_on' and midi_event.velocity > 0:
                # A new note is being pressed, store its starting time position
                active_notes[midi_event.note] = {"time": accDelay, "color": color_idx, "start_idx": message_index}
            elif note_type == 'note_off' or (note_type == 'note_on' and midi_event.velocity == 0):
                # A note is being released, fetch its starting time position
                # to calculate its duration and create a div
                if midi_event.note in active_notes:
                    start_time = active_notes[midi_event.note]["time"]
                    end_time = accDelay
                    duration = end_time - start_time
                    body += (
                        f'<div class = "note tooltip_parent color_{color_class[active_notes[midi_event.note]["color"]]}" style ="left: {start_time*ZOOM}px; top: {(128-midi_event.note) * 10}px; width: {duration*ZOOM}px">'
                        f'<div class="tooltip"> '
                        f'{active_notes[midi_event.note]["start_idx"]}..{message_index} '
                        f'</div>'
                        f'</div>')
                    if start_time+duration > width_roll:
                        width_roll = start_time+duration
                    del active_notes[midi_event.note]  # Remove the note from active_notes
            if message_index in music_splitter.split_data:
                # body += f'<div class="separator" style="left: {accDelay*ZOOM}px;"></div>'
                color_idx += 1
                if color_idx == len(color_class):
                    color_idx = 0

    html = """
      <!DOCTYPE html>
      <html>
      <head>
          <title>Piano Roll</title>
          <style>
              .piano-roll {
                  width: """+str(width_roll*ZOOM)+"""px;
                  height: 1280px;
                  position: relative;
                  background-color: #222;
              }
              .tooltip {
                visibility: hidden;
                position: relative;
                top: -22px;
                left: 17px;
                background-color: yellow;
                z-index: 200;
                font-size: 12px;
                text-align: center;
                width: 100px;
              }

              .tooltip_parent:hover .tooltip {
                  visibility: visible;
              }
              .separator {
                  height: 1280px;
                  top: 0px;
                  background-color: red;
                  width: 2px;
                  position: absolute;
              }
              .measure {
                  height: 1280px;
                  top: 0px;
                  background-color: cyan;
                  width: 1px;
                  position: absolute;
              }         
              .measure_number {
                  position: absolute;
                  top: 0px;
                  width: 30px;
                  z-index: 200;
                  background-color: darkgray;
                  text-align: center;
                  margin-left: 20px;
              }

              .color_green {
                  background-color: lightseagreen;
                  border-top: 1px solid lime;
                  border-left: 1px solid lime;
                  border-right: 1px solid black;
                  border-bottom: 1px solid black;
              }

              .color_yellow {
                  background-color: yellow;
                  border-top: 1px solid white;
                  border-left: 1px solid white;
                  border-right: 1px solid brown;
                  border-bottom: 1px solid brown;
              }

              .color_red {
                  background-color: red;
                  border-top: 1px solid #F88;
                  border-left: 1px solid #F88;
                  border-right: 1px solid #800;
                  border-bottom: 1px solid #800;
              }

              .color_blue {
                  background-color: #44F;
                  border-top: 1px solid #CCF;
                  border-left: 1px solid #CCF;
                  border-right: 1px solid #00C;
                  border-bottom: 1px solid #00C;
              }

              .note {
                  position: absolute;
                  height: 7px;
              }
          </style>
      </head>
      <body>
          <div class="piano-roll">
          """+body+"""
        </div>
    </body>
    </html>
    """

    with open("piano_roll.html", "w") as f:
        f.write(html)


# test()
