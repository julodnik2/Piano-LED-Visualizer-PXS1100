from webinterface import webinterface
from flask import render_template, flash, redirect, request, url_for, jsonify, send_file
from lib.functions import read_only_fs, remove_song, set_read_only
import os

ALLOWED_EXTENSIONS = {'mid', 'musicxml', 'mxl', 'xml', 'abc'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@webinterface.route('/')
def index():
    return render_template('index.html')


@webinterface.route('/home')
def home():
    return render_template('home.html')


@webinterface.route('/ledsettings')
def ledsettings():
    return render_template('ledsettings.html')


@webinterface.route('/piano')
def piano():
    return render_template('piano.html')


@webinterface.route('/ledanimations')
def ledanimations():
    return render_template('ledanimations.html')


@webinterface.route('/songs')
def songs():
    return render_template('songs.html')


@webinterface.route('/sequences')
def sequences():
    return render_template('sequences.html')


@webinterface.route('/ports')
def ports():
    return render_template('ports.html')


@webinterface.route('/upload', methods=['POST'])
def upload_file():
    if request.method == 'POST':
        readonlyfs = read_only_fs()
        if readonlyfs:
            set_read_only(False)
        try:
            if 'file' not in request.files:
                return jsonify(success=False, error="no file")
            file = request.files['file']
            filename = file.filename

            reloadAfter = webinterface.learning.loaded_midi == filename

            if os.path.exists("Songs/" + filename):
                remove_song(filename)

            if not allowed_file(file.filename):
                return jsonify(success=False, error="not a midi file", song_name=filename)

            filename = filename.replace("'", "")
            file.save(os.path.join(webinterface.config['UPLOAD_FOLDER'], filename))
            if reloadAfter:
                webinterface.learning.loaded_midi = None
                webinterface.learning.load_midi(filename)
            return jsonify(success=True, reload_songs=True, song_name=filename)
        finally:
            if readonlyfs:
                set_read_only(True)
