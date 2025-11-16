from nicegui import ui
import queue
import re
import traceback
from io import BytesIO
import asyncio
import threading
import pyaudio
from gtts import gTTS
import pygame
import io
from deep_translator import GoogleTranslator
from google.cloud import speech
import time
from gtts import gTTS

RATE = 16000
CHUNK = int(RATE / 10)  # 100ms chunks

# Supported languages for speech recognition
SPEECH_LANGUAGES = {
    'English': 'en-US',
    'Hindi': 'hi-IN', 
    'Tamil': 'ta-IN',
    'Telugu': 'te-IN',
    'Kannada': 'kn-IN',
    'Malayalam': 'ml-IN',
    'Bengali': 'bn-IN',
    'Marathi': 'mr-IN',
    'Gujarati': 'gu-IN',
    'Punjabi': 'pa-IN',
    'Urdu': 'ur-PK'
}

# Supported languages for translation
TEXT_LANGUAGES = {
    'English': 'en', 'Hindi': 'hi', 'Tamil': 'ta', 'Telugu': 'te', 'Kannada': 'kn',
    'Malayalam': 'ml', 'Bengali': 'bn', 'Marathi': 'mr', 'Gujarati': 'gu', 'Punjabi': 'pa', "Urdu": 'ur'
}

# Global variables
is_listening = False
selected_speech_language = 'English'
selected_text_language = 'English'

selected_input_language = 'English'
selected_output_language = 'English'

# Globals
selected_input_language_tts = 'English'
selected_output_language_tts = 'Hindi'

# globals
is_listening_sts = False
selected_input_language_sts = 'English'
selected_output_language_sts = 'English'
stop_flag = False

selected_output_language_pdf = "Hindi"

pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)



# ------------------------ LANGUAGE SELECTOR ------------------------
def speak_text(text, lang_code):
    """Convert text to speech and play it immediately (no temp file)."""
    try:
        if not text.strip():
            return
            
        tts = gTTS(text=text, lang=lang_code)
        mp3_fp = io.BytesIO()
        tts.write_to_fp(mp3_fp)
        mp3_fp.seek(0)

        # Initialize pygame mixer
        pygame.mixer.init()
        pygame.mixer.music.load(mp3_fp, 'mp3')
        pygame.mixer.music.play()

        # Wait until audio playback finishes
        while pygame.mixer.music.get_busy():
            continue

    except Exception as e:
        print(f"[Error in speech synthesis] {e}")
        ui.notify(f"Speech synthesis error: {e}", type='negative')

# ------------------------ LANGUAGE SELECTOR ------------------------
def language_selector():

    def update_input_language(e):
        global selected_input_language_tts
        selected_input_language_tts = e.value
        ui.notify(f"Input language changed to: {e.value}", type="info")

    def update_output_language(e):
        global selected_output_language_tts
        selected_output_language_tts = e.value
        ui.notify(f"Speech language changed to: {e.value}", type="info")

    with ui.column().classes('w-full max-w-2xl mb-4 gap-4'):
        ui.label("Select Languages").classes("text-black text-xl font-bold text-center")

        with ui.row().classes('w-full justify-around'):
            # Input Language
            with ui.row().classes('language-center'):
                ui.label('Input Language:')
                ui.select(
                    options=list(TEXT_LANGUAGES.keys()),
                    value=selected_input_language_tts,
                    on_change=update_input_language
                ).classes('w-48').props('outlined color=primary dense')

            # Output Language
            with ui.row().classes('language-center'):
                ui.label('Speech Language:')
                ui.select(
                    options=list(TEXT_LANGUAGES.keys()),
                    value=selected_output_language_tts,
                    on_change=update_output_language
                ).classes('w-48').props('outlined color=primary dense')
                
                
def sts_language_selector():
    """Language selector for Speech-to-Speech"""

    def update_input(e):
        global selected_input_language_sts
        selected_input_language_sts = e.value
        ui.notify(f"Input Speech: {e.value}", type="info")

    def update_output(e):
        global selected_output_language_sts
        selected_output_language_sts = e.value
        ui.notify(f"Output Speech: {e.value}", type="info")

    with ui.column().classes('w-full max-w-2xl mb-4 gap-4'):
        ui.label("Select Languages").classes("text-black text-xl font-bold text-center")

        with ui.row().classes('w-full justify-around'):
            # INPUT LANGUAGE
            with ui.row().classes('language-center'):
                ui.label("Input Language:")
                ui.select(
                    options=list(SPEECH_LANGUAGES.keys()),
                    value=selected_input_language_sts,
                    on_change=update_input
                ).classes('w-48').props('outlined dense')

            # OUTPUT LANGUAGE
            with ui.row().classes('language-center'):
                ui.label("Output Language:")
                ui.select(
                    options=list(TEXT_LANGUAGES.keys()),
                    value=selected_output_language_sts,
                    on_change=update_output
                ).classes('w-48').props('outlined dense')


# ---------------- AUDIO STREAM ----------------
class MicrophoneStream:
    """Opens a recording stream as a generator yielding audio chunks."""

    def __init__(self, rate=RATE, chunk=CHUNK):
        self._rate = rate
        self._chunk = chunk
        self._buff = queue.Queue()
        self.closed = True

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,
        )
        self.closed = False
        return self

    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self):
        while not self.closed:
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break
            yield b"".join(data)




def translate_sync(translator, text, dest):
    return asyncio.run(translator.translate(text, dest=dest))

# ---------------- SPEECH RECOGNITION THREAD ----------------
def speech_recognition_thread(text_area):
    """Runs speech recognition in a separate thread"""
    global is_listening, selected_speech_language, selected_text_language
    
    try:
        client = speech.SpeechClient()
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=SPEECH_LANGUAGES[selected_speech_language],
        )
        streaming_config = speech.StreamingRecognitionConfig(
            config=config, interim_results=True
        )

        with MicrophoneStream(RATE, CHUNK) as stream:
            audio_generator = stream.generator()
            requests = (
                speech.StreamingRecognizeRequest(audio_content=content)
                for content in audio_generator
            )

            responses = client.streaming_recognize(streaming_config, requests)
            
            for response in responses:
                if not is_listening:
                    break
                    
                if not response.results:
                    continue
                    
                result = response.results[0]
                if not result.alternatives:
                    continue

                transcript = result.alternatives[0].transcript

                # Update interim result
                if not result.is_final:
                    text_area.value = f"Speaking: {transcript}"
                    text_area.update()
                    continue

                # Final recognized text
                final_text = transcript.strip()
                if final_text:
                    try:
                        # Translate using deep-translator (SYNC)
                        translated_text = GoogleTranslator(
                            source="auto",
                            target=TEXT_LANGUAGES[selected_text_language]
                        ).translate(final_text)

                        text_area.value = (
                            f"Original: {final_text}\n\n"
                            f"{selected_text_language}: {translated_text}"
                        )
                        text_area.update()

                    except Exception as e:
                        text_area.value = (
                            f"Original: {final_text}\n\n"
                            f"Translation Error: {str(e)}"
                        )
                        text_area.update()

                # Exit commands
                if re.search(r"\b(exit|quit|stop)\b", final_text, re.I):
                    stop_listening()
                    break
                        
    except Exception as e:
        text_area.value = f"Error: {str(e)}"
        text_area.update()
        stop_listening()



def start_listening(text_area):
    """Start speech recognition"""
    global is_listening
    if not is_listening:
        is_listening = True
        text_area.value = "🎤 Listening... Speak now!"
        text_area.update()
        # Start speech recognition in a separate thread
        thread = threading.Thread(target=speech_recognition_thread, args=(text_area,))
        thread.daemon = True
        thread.start()
        return "Listening..."
    return "Already listening!"

def stop_listening():
    """Stop speech recognition"""
    global is_listening
    is_listening = False
    return "Stopped listening!"

# ---------------- LANGUAGE SELECTORS ----------------
def speech_language_selector():
    """Creates language selector for speech recognition"""
    def update_speech_language(e):
        global selected_speech_language
        selected_speech_language = e.value
        ui.notify(f'Speech language changed to: {selected_speech_language}', type='info')

    with ui.row().classes('language-center'):
        ui.label('Speech Language:')
        ui.select(options=list(SPEECH_LANGUAGES.keys()),
            value='English', on_change=update_speech_language) \
            .classes('w-48').props('outlined color=primary dense')

def text_language_selector():
    """Creates language selector for text translation"""
    def update_text_language(e):
        global selected_text_language
        selected_text_language = e.value
        ui.notify(f'Text language changed to: {selected_text_language}', type='info')

    with ui.row().classes('language-center'):
        ui.label('Text Language:')
        ui.select(options=list(TEXT_LANGUAGES.keys()),
            value='Hindi', on_change=update_text_language) \
            .classes('w-48').props('outlined color=primary dense')


def input_language_selector():
    """Creates language selector for input text"""
    def update_input_language(e):
        global selected_input_language
        selected_input_language = e.value
        ui.notify(f'Input language changed to: {selected_input_language}', type='info')

    with ui.row().classes('language-center'):
        ui.label('Input Language:')
        ui.select(options=list(TEXT_LANGUAGES.keys()),
            value='English', on_change=update_input_language) \
            .classes('w-48').props('outlined color=primary dense')

def output_language_selector():
    """Creates language selector for output text"""
    def update_output_language(e):
        global selected_output_language
        selected_output_language = e.value
        ui.notify(f'Output language changed to: {selected_output_language}', type='info')

    with ui.row().classes('language-center'):
        ui.label('Output Language:')
        ui.select(options=list(TEXT_LANGUAGES.keys()),
            value='Hindi', on_change=update_output_language) \
            .classes('w-48').props('outlined color=primary dense')


def translate_text(input_text, input_lang, output_lang):
    """Translate text from input language to output language using deep-translator"""
    try:
        src_code = TEXT_LANGUAGES[input_lang]
        dest_code = TEXT_LANGUAGES[output_lang]

        translated = GoogleTranslator(
            source=src_code,
            target=dest_code
        ).translate(input_text)

        return translated

    except Exception as e:
        return f"Translation Error: {str(e)}"



def create_app():
    """Initialize all pages cleanly."""

    # ------------------- WELCOME PAGE -------------------
    @ui.page('/')
    def welcome_page():

        with ui.column().classes(
            'w-full h-screen justify-center items-center bg-gradient-to-b from-black to-blue-900 text-white px-4'
        ):
            ui.label('C.H.R.I.S Tech tools').classes('text-3xl sm:text-4xl font-extrabold mb-3 text-center')
            ui.label('Click get started to explore the tools!').classes('text-gray-400 text-center mb-10')

            ui.button(
                'Get Started',
                on_click=lambda: ui.navigate.to("/home")
            ).classes(
                'bg-blue-600 hover:bg-blue-700 text-white text-lg font-semibold py-3 px-8 rounded-xl shadow-lg transition-all duration-200'
            )


    # ------------------- HOME PAGE -------------------
    @ui.page('/home')
    def home_page():
        ui.add_head_html("""
        <style>
        .feature-card-bg-1 {
            background-image: url('https://ttsfree.com/images/speech-to-text-apps.jpg');
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
        }
        .feature-card-bg-2 {
            background-image: url('https://www.gizmochina.com/wp-content/uploads/2021/04/Google-Translate-Logo-Featured.jpg');
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
        }
        .feature-card-bg-3 {
            background-image: url('https://tse4.mm.bing.net/th/id/OIP.UaI0f8VvJXVluGz16Mb4CQAAAA?cb=ucfimg2ucfimg=1&rs=1&pid=ImgDetMain&o=7&rm=3   ');
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
        }
        .feature-card-bg-4 {
            background-image: url('https://th.bing.com/th/id/OIP.q1zqISWN0nIlIppOuBoXSQHaF7?w=220&h=180&c=7&r=0&o=7&cb=ucfimg2&dpr=1.3&pid=1.7&rm=3&ucfimg=1');
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
        }
        </style>
        """)
        def select_feature(route: str):
            """Navigate to the selected feature's page."""
            ui.navigate.to(f"/{route}")

        with ui.column().classes('w-full h-screen justify-center items-center bg-gradient-to-b from-black to-blue-900 text-white px-4'):
            ui.label('What would you like to do with your Python services?') \
                .classes('text-xl sm:text-2xl font-bold mt-8 mb-4')
            ui.label('Select all that apply').classes('text-md sm:text-lg mb-8')

            # Responsive grid layout
            with ui.grid().classes(
                'grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 sm:gap-6 max-w-screen-xl mx-auto p-4'
            ):

                # ------------------------------

                def feature_card_1(label: str, icon: str, color: str, route: str):
                    """Helper function to create a standardized card."""
                    with ui.card().classes(
                        'w-full h-36 flex flex-col items-center bg-blue-300 hover:bg-green-600 justify-end p-4 cursor-pointer hover:shadow-xl hover:scale-105 transition-all duration-200'
                    ).on('click', lambda: select_feature(route)):
                        ui.icon(icon).classes(f'text-4xl text-{color}-500 mb-2')
                        ui.label(label).classes(
        'text-bottom text-sm sm:text-base font-medium text-white bg-black-50 px-4 py-2 rounded shadow hover:bg-gray-800 cursor-pointer'
    )
                # ------------------------------
                
                def feature_card_2(label: str, icon: str, color: str, route: str):
                    """Helper function to create a standardized card."""
                    with ui.card().classes(
                        'w-full h-36 flex flex-col items-center bg-blue-300 hover:bg-green-600 justify-end p-4 cursor-pointer hover:shadow-xl hover:scale-105 transition-all duration-200'
                    ).on('click', lambda: select_feature(route)):
                        ui.icon(icon).classes(f'text-4xl text-{color}-500 mb-2')
                        ui.label(label).classes(
        'text-bottom text-sm sm:text-base font-medium bg-black-50 text-white px-4 py-2 rounded shadow hover:bg-gray-800 cursor-pointer'
    )
                # ------------------------------
                
                def feature_card_3(label: str, icon: str, color: str, route: str):
                    """Helper function to create a standardized card."""
                    with ui.card().classes(
                        'w-full h-36 flex flex-col items-center bg-blue-300 hover:bg-green-600 justify-end p-4 cursor-pointer hover:shadow-xl hover:scale-105 transition-all duration-200'
                    ).on('click', lambda: select_feature(route)):
                        ui.icon(icon).classes(f'text-4xl text-{color}-500 mb-2')
                        ui.label(label).classes(
        'text-sm sm:text-base font-medium text-white px-4 py-2 bg-black-50 rounded shadow hover:bg-gray-800 cursor-pointer'
    )
                # ------------------------------
                
                def feature_card_4(label: str, icon: str, color: str, route: str):
                    """Helper function to create a standardized card."""
                    with ui.card().classes(
                        'w-full h-36 flex flex-col items-center bg-blue-300 hover:bg-green-600 justify-end p-4 cursor-pointer hover:shadow-xl hover:scale-105 transition-all duration-200'
                    ).on('click', lambda: select_feature(route)):
                        ui.icon(icon).classes(f'text-4xl text-{color}-500 mb-2')
                        ui.label(label).classes(
        'text-bottom text-sm sm:text-base font-medium bg-black-50 text-white px-4 py-2 rounded shadow hover:bg-gray-800 cursor-pointer'
    )
                # ------------------------------
                
                def feature_card_5(label: str, icon: str, color: str, route: str):
                    """Helper function to create a standardized card."""
                    with ui.card().classes(
                        'w-full h-36 flex flex-col items-center bg-blue-300 hover:bg-green-600 justify-end p-4 cursor-pointer hover:shadow-xl hover:scale-105 transition-all duration-200'
                    ).on('click', lambda: select_feature(route)):
                        ui.icon(icon).classes(f'text-4xl text-{color}-500 mb-2')
                        ui.label(label).classes(
        'text-bottom text-sm sm:text-base font-medium bg-black-50 text-white px-4 py-2 rounded shadow hover:bg-gray-800 cursor-pointer'
    )

                # Features Grid (each card routes to its own page)
                feature_card_1('Speech-to-Text','mic', 'red', 'stt')
                feature_card_2('Text Translation','translate' , 'red', 'tt')
                feature_card_3('Speech-to-Speech','headphones', 'red', 'sts')
                feature_card_4('Text-to-speech','equalizer', 'red', 'tts')
                feature_card_5('File Reading','comments', 'red', 'pdf_reader')
                

            # Navigation Buttons
            with ui.row().classes('mt-12 gap-8 mb-8'):
                ui.button(
                    'Back',
                    on_click=lambda: ui.navigate.to("/")
                ).props('flat color=primary')

    # ------------------- FEATURE PAGES (EXAMPLES) -------------------
    @ui.page('/stt')
    def speech_to_text_page():
        global is_listening
        
        ui.add_css('''
        .mic-btn {
            width: 80px;
            height: 80px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background-color: #2563eb; /* blue-600 */
            color: white;
            font-size: 2rem;
            transition: all 0.25s ease-in-out;
            box-shadow: 0 4px 10px rgba(0,0,0,0.3);
        }
        .mic-btn:hover {
            transform: scale(1.1);
            background-color: #1d4ed8; /* blue-700 */
        }
        .mic-btn:active {
            transform: scale(0.95);
            background-color: #1e40af; /* blue-800 */
        }
        .mic-btn-listening {
            background-color: #dc2626 !important; /* red-600 */
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.1); }
            100% { transform: scale(1); }
        }
        
        .white-textarea .q-field__control,
        .white-textarea .q-field__label,
        .white-textarea .q-field__native {
            color: white !important;
        }
        .white-textarea .q-field__inner,
        .white-textarea .q-field__control::before,
        .white-textarea .q-field__control::after {
            border-color: white !important;
        }
        
        .language-center {
            display: flex;
            align-items: center;
            justify-content: center;    
        }
        .language-center label {
            font-weight: 600;
            color: white;
            font-size: 1rem;
            margin-right: 0.5rem;
        }
        .language-center select {
            min-width: 160px;
            padding: 0.4rem 0.8rem;
            border-radius: 8px;
            border-color: white;
            border: 1px solid #2563eb;
            background-color: white;
            color: #111827;
            font-weight: 500;
            box-shadow: 0 1px 4px rgba(0,0,0,0.1);
            transition: all 0.25s ease-in-out;
        }
        .language-center select:hover {
            border-color: #1d4ed8;
            transform: scale(1.03);
        }
        ''')

        with ui.column().classes('w-full h-screen justify-center items-center bg-gradient-to-b from-gray to-blue-900 text-black px-4'):
            # --- Title and Description ---
            ui.label('Speech-to-Text').classes('text-3xl sm:text-4xl font-bold mb-2 text-white-800 text-center')
            ui.label('Click the microphone and start speaking to transcribe your voice in real time.') \
                .classes('text-white-600 text-center mb-6 max-w-2xl')

            # --- Language Selectors ---
            with ui.column().classes('w-full max-w-2xl mb-4 gap-4'):
                ui.label("Select Languages").classes("text-black text-xl font-bold text-center")
                with ui.row().classes('w-full justify-around'):
                    speech_language_selector()
                    text_language_selector()

            # --- Text Area ---
            text_area = ui.textarea(
                label='Transcribed Text',
                placeholder='Your speech will appear here...',
                value=''
            ).classes(
                'black-textarea w-full max-w-2xl mb-6 text-black bg-transparent rounded-xl'
            ).props('rows=6 outlined color=green')

            # --- Microphone Button ---
            mic_button = ui.button(icon='mic', on_click=lambda: toggle_listening(mic_button, text_area)) \
                .classes('mic-btn')

            # --- Status Indicator ---
            status_label = ui.label('Ready to listen').classes('text-lg mb-4')

            # --- Back Button ---
            ui.button('Back', on_click=lambda: ui.navigate.to("/home")) \
                .props('flat color=primary')

        def toggle_listening(button, text_area):
            global is_listening
            if not is_listening:
                # Start listening
                start_listening(text_area)
                button.classes(add='mic-btn-listening')
                status_label.set_text('Listening... Speak now!')
            else:
                # Stop listening
                stop_listening()
                button.classes(remove='mic-btn-listening')
                status_label.set_text('Ready to listen')


    @ui.page('/tt')
    def text_translation_page():
        ui.add_css('''
        .translate-btn {
            background-color: #16a34a; /* green-600 */
            color: white;
            font-size: 1.1rem;
            font-weight: 600;
            padding: 0.8rem 2.5rem;
            border-radius: 9999px; /* fully rounded */
            box-shadow: 0 4px 10px rgba(0,0,0,0.25);
            transition: all 0.25s ease-in-out;
        }
        .translate-btn:hover {
            background-color: #15803d; /* green-700 */
            transform: scale(1.05);
        }
        .translate-btn:active {
            background-color: #166534; /* green-800 */
            transform: scale(0.95);
        }
        
        .white-textarea .q-field__control,
        .white-textarea .q-field__label,
        .white-textarea .q-field__native {
            color: white !important;
        }
        .white-textarea .q-field__inner,
        .white-textarea .q-field__control::before,
        .white-textarea .q-field__control::after {
            border-color: white !important;
        }
        
        .language-center {
            display: flex;
            align-items: center;
            justify-content: center;    
        }
        .language-center label {
            font-weight: 600;
            color: white;
            font-size: 1rem;
            margin-right: 0.5rem;
        }
        .language-center select {
            min-width: 160px;
            padding: 0.4rem 0.8rem;
            border-radius: 8px;
            border-color: white;
            border: 1px solid #2563eb;
            background-color: white;
            color: #111827;
            font-weight: 500;
            box-shadow: 0 1px 4px rgba(0,0,0,0.1);
            transition: all 0.25s ease-in-out;
        }
        .language-center select:hover {
            border-color: #1d4ed8;
            transform: scale(1.03);
        }
        
        .translation-result {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 16px;
            margin-top: 8px;
            border-left: 4px solid #16a34a;
        }
        ''')

        with ui.column().classes('w-full h-screen justify-center items-center bg-gradient-to-b from-gray to-blue-900 text-black px-4'):
            # --- Title and Subtitle ---
            ui.label('Text Translation').classes('text-3xl sm:text-4xl font-bold mb-2 text-white-800 text-center')
            ui.label('Type your text below and click "Translate" to see the output in another language.') \
                .classes('text-white-600 text-center mb-6 max-w-2xl')

            # --- Language Selectors ---
            with ui.column().classes('w-full max-w-2xl mb-4 gap-4'):
                ui.label("Select Languages").classes("text-black text-xl font-bold text-center")
                with ui.row().classes('w-full justify-around'):
                    input_language_selector()
                    

            # --- Input Text Area ---
            input_area = ui.textarea(
                label='Enter text to translate',
                placeholder='Type something here...',
                value=''
            ).classes('black-textarea w-full max-w-2xl mb-4 text-black bg-transparent rounded-xl').props('rows=4 outlined color=green')

            output_language_selector()
            # --- Output Text Area ---
            output_area = ui.textarea(
                label='Translated text',
                placeholder='Translation will appear here...',
                value=''
            ).classes('black-textarea w-full max-w-2xl mb-4 text-black bg-transparent rounded-xl').props('rows=4 outlined color=green')

            # --- Translation Info ---
            translation_info = ui.label('').classes('text-sm text-black-300 mb-2')

            # --- Translate Button ---
            def perform_translation():
                input_text = input_area.value.strip()
                if not input_text:
                    ui.notify('Please enter some text to translate', type='warning')
                    return
                
                # Show translation in progress
                translation_info.set_text(f'Translating from {selected_input_language} to {selected_output_language}...')
                ui.notify('Translation in progress...', type='info')
                
                try:
                    # Perform translation
                    translated_text = translate_text(input_text, selected_input_language, selected_output_language)
                    
                    # Update output area
                    output_area.value = translated_text
                    
                    # Update info
                    translation_info.set_text(f'Translated from {selected_input_language} to {selected_output_language}')
                    ui.notify('Translation completed!', type='positive')
                    
                except Exception as e:
                    error_msg = f'Translation failed: {str(e)}'
                    output_area.value = error_msg
                    translation_info.set_text(error_msg)
                    ui.notify('Translation failed!', type='negative')

            with ui.row().classes('justify-center'):
                ui.button('Translate', on_click=perform_translation) \
                    .classes('translate-btn')

            # --- Clear Button ---
            def clear_text():
                input_area.value = ''
                output_area.value = ''
                translation_info.set_text('')
                ui.notify('Text cleared!', type='info')

            with ui.row().classes('mt-6 gap-8 mb-8'):
                ui.button('Clear', on_click=clear_text) \
                    .props('flat color=primary')

                # --- Back Button ---
                ui.button('Back', on_click=lambda: ui.navigate.to("/home")) \
                    .props('flat color=primary')

   
    # ------------------------ TTS PAGE ------------------------
    @ui.page('/tts')
    def text_to_speech_page():

        ui.add_css("""
        .tts-btn {
            background-color: #2563eb;
            color: white;
            font-size: 1.1rem;
            font-weight: 600;
            padding: 0.8rem 2.5rem;
            border-radius: 9999px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.25);
            transition: all 0.25s ease-in-out;
        }
        .tts-btn:hover { background-color: #1d4ed8; transform: scale(1.05); }
        .tts-btn:active { background-color: #1e40af; transform: scale(0.95); }
        .tts-btn:disabled { background-color: #6b7280; cursor: not-allowed; }

        .white-textarea .q-field__control,
        .white-textarea .q-field__label,
        .white-textarea .q-field__native {
            color: black !important;
        }
        .white-textarea .q-field__inner,
        .white-textarea .q-field__control::before,
        .white-textarea .q-field__control::after {
            border-color: black !important;
        }

        .language-center { display: flex; align-items: center; justify-content: center; }
        .translated-text {
            background: rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 16px;
            margin: 8px 0;
            border-left: 4px solid #2563eb;
            min-height: 80px;
            white-space: pre-wrap;
        }
        """)

        with ui.column().classes('w-full h-screen justify-center items-center bg-gradient-to-b from-gray to-blue-900 text-black px-4'):

            ui.label("Text-to-Speech").classes("text-3xl sm:text-4xl font-bold mb-2 text-center")
            ui.label("Enter text and hear it spoken aloud.").classes("text-black-300 text-center mb-6 max-w-2xl")

            language_selector()

            text_input = ui.textarea(
                label="Enter text to convert to speech",
                placeholder="Type something...",
            ).classes("white-textarea w-full max-w-2xl mb-4 text-white bg-transparent").props("rows=5 outlined")

            translated_display = ui.label("Translation will appear here...").classes("translated-text w-full max-w-2xl mb-4 text-black")

            status_label = ui.label("Ready").classes("text-lg mb-4 text-green-400")

            def generate_speech():
                text_val = text_input.value.strip()
                if not text_val:
                    ui.notify("Please enter some text", type="warning")
                    return

                try:
                    # Update status
                    status_label.set_text("Translating and generating speech...")

                    # Language codes
                    src_lang = TEXT_LANGUAGES[selected_input_language_tts]
                    dest_lang = TEXT_LANGUAGES[selected_output_language_tts]

                    # Translate using deep-translator (SYNC)
                    translated_text = GoogleTranslator(
                        source=src_lang,
                        target=dest_lang
                    ).translate(text_val)

                    # Display translated text
                    translated_display.set_text(translated_text)

                    # Speak the translated text
                    speak_text(translated_text, dest_lang)

                    # Update status
                    status_label.set_text("Translation and speech completed!")
                    ui.notify("Text translated and spoken successfully!", type="positive")

                except Exception as e:
                    status_label.set_text("Error occurred")
                    ui.notify(f"Error: {str(e)}", type="negative")
                    print(f"Error: {e}")


            ui.button("Generate Speech", on_click=generate_speech).classes("tts-btn")

            ui.button("Back", on_click=lambda: ui.navigate.to("/home")).props("flat color=primary mt-8")

    # -------------------- PAGE: /sts --------------------
    @ui.page('/sts')
    def speech_to_speech_page():
        ui.add_css('''
        .mic-btn {
            width: 80px;
            height: 80px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background-color: #dc2626;
            color: white;
            font-size: 2rem;
            transition: all 0.25s ease-in-out;
            box-shadow: 0 4px 10px rgba(0,0,0,0.3);
        }
        .mic-btn:hover { transform: scale(1.1); background-color: #b91c1c; }
        .mic-btn:active { transform: scale(0.95); background-color: #991b1b; }

        .white-textarea .q-field__control,
        .white-textarea .q-field__label,
        .white-textarea .q-field__native { color: black !important; }
        .white-textarea .q-field__inner,
        .white-textarea .q-field__control::before,
        .white-textarea .q-field__control::after { border-color: black !important; }
        ''')

        with ui.column().classes(
            'w-full h-screen justify-center items-center bg-gradient-to-b from-gray to-blue-900 text-black px-4'
        ):
            ui.label('Speech-to-Speech').classes(
                'text-3xl sm:text-4xl font-bold mb-2 text-center'
            )
            ui.label(
                'Click the microphone to speak. Your speech will be translated and spoken immediately.'
            ).classes('text-black-600 text-center mb-6 max-w-2xl')

            sts_language_selector()

            # text area
            text_input = ui.textarea(
                label='Translated Speech Output',
                placeholder='Speak into the microphone...',
                value=''
            ).classes(
                'white-textarea w-full max-w-2xl mb-6 text-black bg-transparent rounded-xl'
            ).props('rows=5 outlined color=green')

            # buttons
            with ui.row().classes('justify-center mb-10 gap-6'):
                ui.button(
                    icon='mic',
                    on_click=lambda: sts_start(text_input),
                ).classes('mic-btn')

                ui.button(
                    'Stop',
                    on_click=sts_stop,
                ).classes(
                    'bg-red-600 hover:bg-red-700 text-white font-semibold py-3 px-6 rounded-full'
                )

            ui.button('Back', on_click=lambda: ui.navigate.to("/home")).props('flat color=primary')

    # ====================== UI PAGE ======================
    @ui.page('/pdf_reader')
    def pdf_reader():
        ui.add_css("""
        .upload-btn {
            background-color: #2563eb;
            color: white;
            font-size: 1.05rem;
            font-weight: 600;
            padding: 0.7rem 1.8rem;
            border-radius: 6px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.25);
            transition: all 0.18s ease-in-out;
            height: 10%;
        }
        .upload-btn:hover { background-color: #1d4ed8; transform: scale(1.03); }
        .white-area {
            background: rgba(255,255,255,0.06);
            border-radius: 12px;
            padding: 16px;
            border-left: 4px solid #2563eb;
            height: 300px;
            overflow-y: auto;
            white-space: normal;
        }
        .click-word {
            color: #60a5fa;
            cursor: pointer;
            padding: 2px 6px;
            font-size: 1.05rem;
            margin: 2px;
        }
        .click-word:hover { color: #93c5fd; text-decoration: underline; }
        """)

        with ui.column().classes('w-full h-screen justify-center items-center bg-gradient-to-b from-gray to-blue-900 text-black px-4'):
            ui.label("PDF / Image Word Reader").classes("text-3xl sm:text-4xl font-bold mb-2 text-center")
            ui.label("Upload a document and click any word to hear it spoken and translated.").classes("text-black-300 text-center mb-6 max-w-2xl")

            # language selector (output)
            def on_lang_change(e):
                global selected_output_language_pdf
                selected_output_language_pdf = e.value
                ui.notify(f'Output language set to: {e.value}', type='info')

            with ui.row().classes('w-full max-w-2xl justify-center mb-3'):
                ui.label('Output Language:').classes('mr-4')
                ui.select(options=list(TEXT_LANGUAGES.keys()), value=selected_output_language_pdf, on_change=on_lang_change).classes('w-48 color = white').props('outlined color=primary dense')

            ui.label("Extracted Text").classes("text-xl font-semibold mb-2 text-black-300")

            # container for extracted text (clickable words)
            text_area_container = ui.column().classes('white-area w-full max-w-3xl mb-2')

            ui.upload(
                label="Upload File",
                auto_upload=True,
                on_upload=lambda e: process_file_for_reader(e, text_area_container)
            ).props("accept='.pdf,.png,.jpg,.jpeg'").classes("upload-btn mb-4")


            ui.button("Back", on_click=lambda: ui.navigate.to("/home")).props("flat color=primary mt-8")

# ----------------- TTS + translate worker -----------------
def _play_mp3_bytes_nonblocking(mp3_bytes: bytes):
    """
    Plays mp3 bytes via pygame in a background thread.
    If a playback is already active it stops it and plays the new one.
    """
    try:
        # load into BytesIO
        buf = io.BytesIO(mp3_bytes)
        # pygame supports file-like if given 'mp3' (works in many setups)
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(buf, 'mp3')
            pygame.mixer.music.play()
            # don't block the caller: return immediately, playback happens in mixer thread
        except Exception:
            # fallback: write a small loop to ensure it at least tries
            buf.seek(0)
            tmp = buf.read()
            pygame.mixer.music.stop()
            pygame.mixer.music.load(io.BytesIO(tmp), 'mp3')
            pygame.mixer.music.play()
    except Exception as e:
        print('TTS playback error:', e)

def speak_and_translate_word_background(word: str, dest_short: str):
    """Runs in background thread: speaks original word then translated word."""
    try:
        # speak original (assume English as source; you can change)
        try:
            tts = gTTS(text=word, lang='en')
            b = io.BytesIO()
            tts.write_to_fp(b)
            b.seek(0)
            _play_mp3_bytes_nonblocking(b.read())
            # wait until finished before continuing (optional short delay)
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
        except Exception:
            # ignore original tts errors
            pass

        # translate
        try:
            translated = GoogleTranslator(source='auto', target=dest_short).translate(word)
        except Exception as e:
            translated = f"[translate error] {word}"

        # speak translated
        try:
            tts2 = gTTS(text=translated, lang=dest_short)
            b2 = io.BytesIO()
            tts2.write_to_fp(b2)
            b2.seek(0)
            _play_mp3_bytes_nonblocking(b2.read())
        except Exception as e:
            print('TTS2 error', e)
    except Exception as e:
        print('speak_and_translate_word_background error:', e)

def speak_and_translate_word(word: str):
    """Start background thread for TTS + translation for clicked word."""
    # get destination short code from global selected_output_language_pdf
    dest_name = globals().get(selected_output_language_pdf)
    dest_short = TEXT_LANGUAGES.get(dest_name, 'en')
    threading.Thread(target=speak_and_translate_word_background, args=(word, dest_short), daemon=True).start()

# ----------------- render extracted text as clickable words -----------------
def render_click_words(text, container):
    container.clear()

    lines = text.split("\n")

    for line in lines:
        # Create row INSIDE container using "with"
        with container:
            row = ui.row().classes("flex-wrap w-full")
        
        for w in line.split():
            with row:  # Place labels inside the row
                ui.label(w)\
                    .classes("click-word")\
                    .on("click", lambda _, word=w: speak_and_translate_word(word))


# ----------------- file processing handler -----------------
async def process_file_for_reader(event, container):
    try:
        file = event.file   # SmallFileUpload
        
        # ---- NEW FIX: read file bytes asynchronously ----
        file_bytes = await file.read()           # ← THIS IS THE FIX
        file_name = file.name.lower()

        # Decide file type
        text = ""

        if file_name.endswith(".pdf"):
            import PyPDF2
            pdf_stream = io.BytesIO(file_bytes)
            reader = PyPDF2.PdfReader(pdf_stream)
            for page in reader.pages:
                t = page.extract_text() or ""
                text += t + "\n"

        else:
            from PIL import Image
            import pytesseract
            img = Image.open(io.BytesIO(file_bytes))
            text = pytesseract.image_to_string(img)

        # Render extracted text
        render_click_words(text, container)
        ui.notify("File processed successfully!", type="positive")

    except Exception as e:
        ui.notify(f"Error: {e}", type="negative")
        print("UPLOAD ERROR:", e)


    except Exception as e:
        traceback.print_exc()
        ui.notify(f'Processing error: {e}', type='negative')
        
        
def speak_and_translate_word(word):
    target = TEXT_LANGUAGES[selected_output_language_pdf]

    def run():
        try:
            # speak original English word
            fp1 = BytesIO()
            gTTS(text=word, lang="en").write_to_fp(fp1)
            fp1.seek(0)
            pygame.mixer.music.load(fp1, "mp3")
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pass

            # translate
            translated = GoogleTranslator(source="auto", target=target).translate(word)

            # speak translated
            fp2 = BytesIO()
            gTTS(text=translated, lang=target).write_to_fp(fp2)
            fp2.seek(0)
            pygame.mixer.music.load(fp2, "mp3")
            pygame.mixer.music.play()

        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")

    threading.Thread(target=run, daemon=True).start()



def sts_start(text_area):
    global is_listening_sts

    if is_listening_sts:
        ui.notify("Already listening...", type='warning')
        return

    is_listening_sts = True
    ui.notify("Listening...", type='info')

    threading.Thread(
        target=sts_recognition_thread,
        args=(text_area,),
        daemon=True
    ).start()


def sts_stop():
    global is_listening_sts
    is_listening_sts = False
    pygame.mixer.music.stop()
    ui.notify("Stopped", type='warning')



def sts_recognition_thread(text_area):

    global is_listening_sts
    is_listening_sts = True

    # --- Google Speech ---
    try:
        speech_client = speech.SpeechClient()
    except Exception as e:
        ui_safe(lambda: ui.notify(f"Google Speech Error: {e}", type='negative'))
        return

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code=SPEECH_LANGUAGES[selected_input_language_sts],
        enable_automatic_punctuation=True,
    )

    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=True,
        single_utterance=False
    )

    dest_lang = TEXT_LANGUAGES[selected_output_language_sts]

    try:
        with MicrophoneStream(RATE, CHUNK) as stream:

            audio_gen = stream.generator()
            requests = (
                speech.StreamingRecognizeRequest(audio_content=c)
                for c in audio_gen
            )
            responses = speech_client.streaming_recognize(streaming_config, requests)

            for response in responses:

                if not is_listening_sts:
                    break

                if not response.results:
                    continue

                result = response.results[0]
                if not result.alternatives:
                    continue

                transcript = result.alternatives[0].transcript.strip()

                # ---------------- INTERIM TEXT ----------------
                if not result.is_final:
                    ui_safe(lambda t=transcript: ui_set_text(text_area, f"{t}"))
                    continue

                # ---------------- FINAL → TRANSLATE ----------------
                try:
                    translated = GoogleTranslator(
                        source='auto',
                        target=dest_lang
                    ).translate(transcript)
                except Exception as e:
                    translated = f"Translation Error: {e}"

                # UPDATE UI
                ui_safe(lambda t=translated: ui_set_text(text_area, t))

                # ---------------- SPEAK TRANSLATION ----------------
                try:
                    tts = gTTS(text=translated, lang=dest_lang)
                    buf = io.BytesIO()
                    tts.write_to_fp(buf)
                    buf.seek(0)
                    pygame.mixer.music.load(buf, "mp3")
                    pygame.mixer.music.play()
                except Exception as e:
                    ui_safe(lambda: ui.notify(f"TTS Error: {e}", type='negative'))

                # ---------------- EXIT WORD ----------------
                if re.search(r"\b(exit|quit|stop)\b", transcript, re.I):
                    is_listening_sts = False
                    ui_safe(lambda: ui.notify("Stopped by voice command", type='warning'))
                    break

    except Exception as e:
        ui_safe(lambda: ui_set_text(text_area, f"Error: {e}"))
        is_listening_sts = False



# ---------------- SAFE UI WRAPPERS ----------------

def ui_safe(fn):
    """Schedule UI changes from background thread safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(fn)
    except:
        pass


def ui_set_text(element, text):
    """Set textarea text safely using JavaScript."""
    try:
        element_id = element.id
        safe_text = text.replace("`", "'")
        ui.context.client.run_javascript(
            f"document.querySelector('[data-id=\"{element_id}\"] textarea').value = `{safe_text}`;"
        )
    except:
        pass





# ------------------- RUN APP -------------------
if __name__ in {"__main__", "__mp_main__"}:
    create_app()
    ui.run(title="CHRIS's tech")
