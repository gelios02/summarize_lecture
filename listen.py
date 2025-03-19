import os
import re
import shutil
import httpx
from time import sleep
from pydub import AudioSegment
from deepgram import (
    DeepgramClient,
    PrerecordedOptions,
    FileSource,
)


# Deepgram API Key
DEEPGRAM_API_KEY = "2334301f06d4d22858fb909e77daa506504dd5d5"

# Допустимые форматы аудиофайлов
ALLOWED_AUDIO_FORMATS = (".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg")

RETRY_LIMIT = 15
TEMP_DIRECTORY = "D://lemon/summarize_lecture/listener_temp"

def check_and_clear_temp_directory():
    """
    Проверяет наличие временной папки и очищает её перед использованием.
    """
    if not os.path.exists(TEMP_DIRECTORY):
        os.makedirs(TEMP_DIRECTORY)
    else:
        for file in os.listdir(TEMP_DIRECTORY):
            file_path = os.path.join(TEMP_DIRECTORY, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Ошибка при очистке временной папки: {e}")

def copy_to_temp_directory(file_path):
    """
    Копирует файл в временную папку с безопасным именем.
    """
    try:
        sanitized_filename = re.sub(r'[^a-zA-Z0-9_.]', '_', os.path.basename(file_path))
        temp_file_path = os.path.join(TEMP_DIRECTORY, sanitized_filename)
        shutil.copy(file_path, temp_file_path)
        return temp_file_path
    except Exception as e:
        print(f"Ошибка копирования файла в временную папку: {e}")
        return None

def retry_function(func, *args, **kwargs):
    """
    Выполняет функцию с заданным числом повторов в случае ошибки.
    """
    for attempt in range(RETRY_LIMIT):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"Ошибка в {func.__name__}: {e}. Попытка {attempt + 1} из {RETRY_LIMIT}...")
            sleep(2)
    return None

def convert_to_wav(file_path):
    """
    Конвертирует файл в формат WAV (16kHz, моно) и сохраняет в TEMP_DIRECTORY.
    """
    try:
        audio = AudioSegment.from_file(file_path)
        audio = audio.set_frame_rate(16000).set_channels(1)
        output_path = os.path.join(TEMP_DIRECTORY, os.path.basename(file_path).rsplit('.', 1)[0] + '_converted.wav')
        audio.export(output_path, format="wav")
        return output_path
    except Exception as e:
        print(f"Ошибка конвертации: {e}")
        return None


def reduce_bitrate(file_path):
    """
    Максимально уменьшает битрейт, частоту дискретизации и число каналов аудиофайла.
    """
    try:
        # Загружаем аудио
        audio = AudioSegment.from_file(file_path)

        # Применяем преобразования: частота дискретизации 4000 Гц, моно-канал
        audio = audio.set_frame_rate(4000).set_channels(1)

        # Указываем путь для сохранения уменьшенного файла
        output_path = os.path.join(TEMP_DIRECTORY, os.path.basename(file_path).rsplit('.', 1)[0] + '_reduced.wav')

        # Экспортируем аудио с минимальным битрейтом
        audio.export(output_path, format="wav", bitrate="16k")

        return output_path
    except Exception as e:
        print(f"Ошибка уменьшения битрейта: {e}")
        return None


def transcribe_audio(file_path, language):
    """
    Распознает речь из локального аудиофайла через Deepgram API.
    """
    try:
        check_and_clear_temp_directory()

        if not os.path.exists(file_path):
            return "Ошибка: файл не найден."

        temp_file_path = copy_to_temp_directory(file_path)
        if not temp_file_path:
            return "Ошибка: не удалось скопировать файл в временную папку."

        if not temp_file_path.endswith(".wav"):
            print("Конвертация в WAV...")
            temp_file_path = retry_function(convert_to_wav, temp_file_path)
            if not temp_file_path:
                return "Ошибка: не удалось конвертировать файл в WAV."

        print("Уменьшение битрейта...")
        temp_file_path = retry_function(reduce_bitrate, temp_file_path)
        if not temp_file_path:
            return "Ошибка: не удалось уменьшить битрейт файла."

        deepgram = DeepgramClient(DEEPGRAM_API_KEY)
        print("Клиент Deepgram инициализирован.")

        for attempt in range(RETRY_LIMIT):
            try:
                with open(temp_file_path, "rb") as file:
                    buffer_data = file.read()

                payload: FileSource = {"buffer": buffer_data}
                options = PrerecordedOptions(
                    model="nova-2",
                    language=language,
                    smart_format=True,

                )
                myTimeout = httpx.Timeout(300.0, connect=100.0)
                response = deepgram.listen.rest.v("1").transcribe_file(payload, options, timeout=myTimeout)
                transcript = response["results"]["channels"][0]["alternatives"][0]["transcript"]

                if not transcript.strip():
                    return "В аудиофайле отсутствует речь, которую можно обработать."

                # print("Распознанный текст:", transcript)
                return transcript

            except Exception as e:
                print(f"Ошибка при распознавании: {e}. Попытка {attempt + 1} из {RETRY_LIMIT}...")
                sleep(2)

        return "Ошибка: не удалось распознать аудио после нескольких попыток."

    except Exception as e:
        print(f"Ошибка: {e}")
        return None

# if __name__ == "__main__":
#     file_path = "english_ru.wav"
#     language = "ru"
#     result = transcribe_audio(file_path, language)
#
#     if result:
#         print(result)
