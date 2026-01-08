import pyaudio
import numpy as np
import threading
import time

class Scorer:
    """
    Sistema de Pontuação (Scorer) baseado na detecção de energia do microfone.
    
    Funciona comparando momentos de "Canto Esperado" (definidos pelo player baseados nos timestamps das letras)
    com a entrada real do microfone. Se o jogador emitir som (energia acima de um limiar) durante
    um segmento de canto, ele ganha pontos.
    
    Atributos:
        rate (int): Taxa de amostragem do áudio (padrão 44100Hz).
        chunk (int): Tamanho do buffer de áudio.
        running (bool): Flag de controle da thread de análise.
        is_singing_segment (bool): Flag definida externamente pelo Player para indicar se agora é hora de cantar.
    """
    def __init__(self, rate=44100, chunk=1024):
        self.rate = rate
        self.chunk = chunk
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.running = False
        self.current_score = 0
        self.total_samples = 0
        self.hit_samples = 0
        self.is_singing_segment = False

    def start(self):
        try:
            self.stream = self.p.open(format=pyaudio.paInt16,
                                      channels=1,
                                      rate=self.rate,
                                      input=True,
                                      frames_per_buffer=self.chunk)
            self.running = True
            self.thread = threading.Thread(target=self._analyze)
            self.thread.start()
        except OSError:
            print("Nenhum microfone detectado. A pontuação será simulada.")
            self.running = False

    def stop(self):
        self.running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.p.terminate()

    def set_singing_segment(self, is_active):
        """
        Define se o momento atual é um segmento de canto válido.
        Chamado pelo KaraokePlayer com base nos timestamps da letra.
        """
        self.is_singing_segment = is_active

    def _analyze(self):
        """
        Método executado em thread separada para analisar o áudio do microfone continuamente.
        Calcula o volume (RMS) e verifica se supera o limiar de silêncio durante segmentos de canto.
        """
        while self.running:
            try:
                data = self.stream.read(self.chunk, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)

                # Detecção Simples de Ritmo/Energia
                volume = np.linalg.norm(audio_data) / self.chunk

                # Limiar para considerar que está "cantando"
                threshold = 10.0 # Limiar arbitrário baixo para sensibilidade

                if self.is_singing_segment:
                    self.total_samples += 1
                    if volume > threshold:
                        self.hit_samples += 1

            except Exception as e:
                print(f"Erro de Áudio: {e}")
                break

    def get_score(self):
        """Retorna a pontuação atual normalizada de 0 a 100."""
        if self.total_samples == 0:
            return 0
        # Calcula a porcentagem de tempo que o usuário cantou durante os segmentos ativos
        accuracy = (self.hit_samples / self.total_samples) * 100

        # Escala para nota 0-100
        return int(min(100, accuracy))

    def reset(self):
        self.total_samples = 0
        self.hit_samples = 0
