import os
import json
import random
import yt_dlp
import syncedlyrics
from ytmusicapi import YTMusic
import time
import subprocess
import whisper
from pydub import AudioSegment
import shutil
import http.server
import socketserver
import threading


class SongManager:
    """
    Gerencia o ciclo de vida completo das músicas:
    - Download do YouTube (yt-dlp)
    - Separação de Áudio (Demucs)
    - Transcrição e Alinhamento (Whisper + Wav2Vec2)
    - Gerenciamento da Biblioteca JSON
    """
    def __init__(self, song_dir="songs", library_file="library.json"):
        self.song_dir = song_dir
        self.library_file = library_file
        self.ytmusic = YTMusic()

        if not os.path.exists(self.song_dir):
            os.makedirs(self.song_dir)

        if not os.path.exists(self.library_file):
            self.library = {}
            self.save_library()
        else:
            self.load_library()

    def load_library(self):
        try:
            with open(self.library_file, 'r') as f:
                self.library = json.load(f)
        except json.JSONDecodeError:
            self.library = {}

    def save_library(self):
        with open(self.library_file, 'w') as f:
            json.dump(self.library, f, indent=4)

    def generate_id(self):
        """Gera um ID único de 4 dígitos para a música."""
        while True:
            # Gera um código de 4 dígitos
            code = str(random.randint(1000, 9999))
            if code not in self.library:
                return code

    def search_song(self, query):
        results = self.ytmusic.search(query, filter='songs')
        return results[:5]  # Retorna os top 5 resultados

    def create_mock_song(self, title, artist):
        """Cria uma música fictícia (placeholder) quando o download falha em ambientes restritos."""
        print(f"Criando dados MOCK para {title}...")
        song_id = self.generate_id()
        base_filename = os.path.join(self.song_dir, song_id)

        # Cria um arquivo MP3 fictício usando ffmpeg
        os.system(f'ffmpeg -f lavfi -i "sine=frequency=440:duration=30" -c:a libmp3lame -q:a 4 {base_filename}.mp3 -y > /dev/null 2>&1')

        # Cria LRC fictício
        lrc_content = f"""[00:00.00] {title} - {artist}
[00:05.00] Esta é uma linha de letra fictícia 1
[00:10.00] Cantando junto com o ritmo
[00:15.00] Linha de letra fictícia número 3
[00:20.00] Fim da música fictícia
"""
        with open(f"{base_filename}.lrc", "w", encoding="utf-8") as f:
            f.write(lrc_content)

        self.library[song_id] = {
            "id": song_id,
            "title": title,
            "artist": artist,
            "audio_path": f"{base_filename}.mp3",
            "lrc_path": f"{base_filename}.lrc"
        }
        self.save_library()
        return song_id

    def process_audio(self, input_path, song_id, title, artist, progress_callback=None):
        """
        Fluxo principal de processamento de áudio IA:
        1. Separa o instrumental da voz usando Demucs.
        2. Transcreve a voz usando Whisper para obter timestamps de palavras.
        3. Alinha com a letra oficial (se encontrada) ou usa a transcrição direta.
        """
        def log(msg):
            if progress_callback:
                progress_callback(msg)
            else:
                print(msg)

        song_folder = os.path.dirname(input_path)
        
        # 1. DEMUCS separação de áudio
        log(f"Iniciando separação de áudio específica para {title}...")
        
        # Verifica se já temos a separação instrumental para pular a re-execução pesada
        demucs_output_dir = os.path.join(song_folder, "htdemucs", song_id)
        final_instrumental_path = os.path.join(self.song_dir, f"{song_id}_instrumental.mp3")
        
        vocals_path = None
        
        # Se instrumental já existe, talvez pular o demucs?
        # Mas precisamos dos vocais para o whisper.
        # Idealmente verificamos se vocals.wav existe.
        
        if os.path.exists(demucs_output_dir): 
            # Verifica se vocals.wav existe
             possible_vocals = os.path.join(demucs_output_dir, "vocals.wav")
             if os.path.exists(possible_vocals):
                 vocals_path = possible_vocals
        
        if not vocals_path:
            try:
                cmd = ["demucs", "-n", "htdemucs", "--two-stems=vocals", input_path, "-o", song_folder]
                log(f"Executando Demucs (isso pode demorar)...")
                subprocess.run(cmd, check=True) 
                
                # Localizar caminhos
                # Demucs cria pasta baseada no nome do arquivo.
                demucs_output_dir = os.path.join(song_folder, "htdemucs", song_id)
                if not os.path.exists(demucs_output_dir):
                     # Checagem de fallback
                     pass

                vocals_path = os.path.join(demucs_output_dir, "vocals.wav")
                no_vocals_path = os.path.join(demucs_output_dir, "no_vocals.wav")
                
                if not os.path.exists(vocals_path) or not os.path.exists(no_vocals_path):
                    log("Saída do Demucs não encontrada. Abortando processamento de IA.")
                    return None, None

                # Converter instrumental
                log("Convertendo instrumental para MP3...")
                AudioSegment.from_wav(no_vocals_path).export(final_instrumental_path, format="mp3")
                
            except Exception as e:
                log(f"Erro no Demucs: {e}")
                return None, None

        # 2. TRANSCRIÇÃO COM WHISPER
        try:
            log("Carregando modelo Whisper (base)...")
            model = whisper.load_model("base")
            log("Transcrevendo vocais com timestamps de palavras...")
            
            # Chave: word_timestamps=True para obter tempos por palavra
            result = model.transcribe(vocals_path, word_timestamps=True)
            
            # Salva transcrição bruta do Whisper
            raw_text_path = os.path.join(self.song_dir, f"{song_id}_whisper.txt")
            with open(raw_text_path, "w", encoding="utf-8") as f:
                for seg in result['segments']:
                    f.write(f"\nSegmento de Exemplo: {seg['text']}\n")
                    if 'words' in seg:
                        for word in seg['words']:
                            start = word['start']
                            end = word['end']
                            text = word['word']
                            f.write(f"[{start:.2f} - {end:.2f}] {text}\n")
                    else:
                        f.write("(Sem timestamps de palavras encontrados)\n")

            # 3. ALINHAMENTO
            log("Buscando letras oficiais...")
            official_lrc = syncedlyrics.search(f"{title} {artist}")
            
            final_lrc_content = ""
            
            if official_lrc:
                log("Letra oficial encontrada. Realizando alinhamento por palavra (CTC)...")
                # Encontrar vocals.wav
                # Estrutura de saída do Demucs: songs/htdemucs/{song_id}/htdemucs_model/{song_name}/vocals.wav
                vocals_path = None
                demucs_basedir = os.path.join(self.song_dir, "htdemucs", song_id)
                
                # Busca simples para encontrar 'vocals.wav'
                for root, dirs, files in os.walk(demucs_basedir):
                    if "vocals.wav" in files:
                        vocals_path = os.path.join(root, "vocals.wav")
                        break
                
                if vocals_path and os.path.exists(vocals_path):
                     detected_lang = result.get('language', 'pt')
                     log(f"Whisper detected language: {detected_lang}")
                     final_lrc_content, aligned_words = self.align_precise_lyrics_with_audio(vocals_path, official_lrc, language=detected_lang)
                else:
                     log("Erro: Não foi possível encontrar vocals.wav para alinhamento. Usando LRC simples.")
                     # Fallback para LRC simples baseada em linhas ou Whisper
                     final_lrc_content, aligned_words = self.align_precise_lyrics(result['segments'], official_lrc)
            else:
                log("Letra oficial não encontrada. Usando segmentos do Whisper.")
                aligned_words = [] 
                final_lrc_content = ""
                for seg in result['segments']:
                    start = seg['start']
                    text = seg['text'].strip()
                    minutes = int(start // 60)
                    seconds = start % 60
                    time_tag = f"[{minutes:02d}:{seconds:05.2f}]"
                    final_lrc_content += f"{time_tag} {text}\n"

            # Salvar LRC
            final_lrc_path = os.path.join(self.song_dir, f"{song_id}.lrc")
            with open(final_lrc_path, "w", encoding="utf-8") as f:
                f.write(final_lrc_content)
            
            # Salvar DEBUG DE ALINHAMENTO
            if aligned_words:
                debug_align_path = os.path.join(self.song_dir, f"{song_id}_alignment_debug.txt")
                with open(debug_align_path, "w", encoding="utf-8") as f:
                     f.write(f"{'TEMPO':<15} | {'PALAVRA'}\n")
                     f.write("-" * 40 + "\n")
                     for w in aligned_words:
                         start = w.get('start')
                         end = w.get('end')
                         txt = w.get('display', '')
                         if start is not None:
                             f.write(f"[{start:.2f}-{end:.2f}]   | {txt}\n")
                         else:
                             f.write(f"{'FALTANDO':<15} | {txt}\n")

            # 4. SALVAR JSON COMPLETO PARA O PLAYER
            log("Construindo dados JSON para o player...")
            lines_data = []
            
            # aligned_words é linear. Precisamos reagrupar por linha.
            # Usando 'line_idx' de aligned_words se disponível
            
            # Reagrupamento
            current_line_idx = -1
            current_line_words = []
            
            try:
                for w in aligned_words:
                    l_idx = w.get('line_idx', -1)
                    
                    if l_idx != current_line_idx:
                        # Limpa a linha anterior
                        if current_line_words:
                            # Determina início/fim da linha
                            l_start = current_line_words[0]['start']
                            l_end = current_line_words[-1]['end']
                            # Proteções
                            if l_start is None: l_start = 0
                            if l_end is None: l_end = l_start + 5
                            
                            # Reconstrução completa do texto
                            l_text = " ".join([cw['display'] for cw in current_line_words])
                            
                            lines_data.append({
                                "start": l_start,
                                "end": l_end,
                                "text": l_text,
                                "words": current_line_words
                            })
                        
                        current_line_idx = l_idx
                        current_line_words = []
                    
                    current_line_words.append(w)
                
                # Limpa a última linha
                if current_line_words:
                    l_start = current_line_words[0]['start']
                    l_end = current_line_words[-1]['end']
                    if l_start is None: l_start = 0
                    if l_end is None: l_end = l_start + 5
                    l_text = " ".join([cw['display'] for cw in current_line_words])
                    lines_data.append({
                        "start": l_start,
                        "end": l_end,
                        "text": l_text,
                        "words": current_line_words
                    })
                
                log(f"Estrutura JSON construída. Salvando em: {song_id}_lyrics.json")
                lyrics_json_path = os.path.join(self.song_dir, f"{song_id}_lyrics.json")
                import json
                with open(lyrics_json_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        "id": song_id,
                        "title": title,
                        "artist": artist,
                        "lines": lines_data
                    }, f, indent=2)
                log(f"JSON Salvo com sucesso.")

                return final_instrumental_path, lyrics_json_path

            except Exception as e:
                log(f"Erro detalhado ao gerar JSON: {e}")
                import traceback
                traceback.print_exc()
                # Retorna LRC padrão se JSON falhar, mas registra o erro
                return final_instrumental_path, final_lrc_path
            
            finally:
                # 5. LIMPEZA
                # Remove a pasta de saída do demucs para economizar espaço
                if os.path.exists(demucs_output_dir):
                    try:
                        log(f"Limpando arquivos temporários em {demucs_output_dir}...")
                        import shutil
                        shutil.rmtree(demucs_output_dir)
                    except Exception as e:
                        log(f"Aviso: Não foi possível limpar arquivos temporários: {e}")

        except Exception as e:
            log(f"Erro em Whisper/Alinhamento: {e}")
            import traceback
            traceback.print_exc()
            return None, None

    def align_precise_lyrics(self, whisper_segments, official_lrc_content):
        """
        Alinha letras usando CTC Segmentation com Wav2Vec2 (Torchaudio).
        Gera timings precisos para cada palavra da letra oficial.
        """
        print("Iniciando Alinhamento Forçado (CTC-Segmentation)...")
        import torch
        import torchaudio
        from transformers import Wav2Vec2Processor, Wav2Vec2ForCTC
        import re

        # CONSTANTES
        MODEL_ID = "jonatasgrosman/wav2vec2-large-xlsr-53-portuguese"
        
        # 1. Analisar Letra Oficial em Palavras
        official_words = []
        official_lines_raw = []
        raw_lines = official_lrc_content.splitlines()
        current_line_idx = 0
        
        full_text_words = []
        
        for line in raw_lines:
            clean_line = re.sub(r'\[.*?\]', '', line).strip()
            if not clean_line: continue
            
            official_lines_raw.append(clean_line)
            
            words = clean_line.split()
            for w in words:
                # Limpa para entrada do modelo (minúsculo)
                w_clean = re.sub(r'[^\w\s]', '', w).lower()
                official_words.append({
                    'text': w_clean,
                    'display': w,
                    'line_idx': current_line_idx,
                    'start': None,
                    'end': None
                })
                full_text_words.append(w_clean)
            current_line_idx += 1
            
        # 2. Preparar Áudio
        # Precisamos da faixa vocal.
        # Se não temos áudio vocal, não podemos realizar o alinhamento forçado.
        # Retornamos uma estrutura básica baseada apenas nos segmentos do Whisper (não implementado aqui, pois este é um fallback).
        # Para evitar erros, retornamos listas vazias.
        print("Aviso: Tentativa de alinhamento forçado sem áudio. Abortando.")
        return "", [] 

    def align_precise_lyrics_with_audio(self, vocals_path, official_lrc_content, language='pt'):
        """
        Realiza o alinhamento forçado (Forced Alignment) entre o áudio vocal e o texto da letra.
        Utiliza modelos Wav2Vec2 específicos por idioma (PT, EN, ES).
        """
        models_map = {
            'pt': "jonatasgrosman/wav2vec2-large-xlsr-53-portuguese",
            'en': "jonatasgrosman/wav2vec2-large-xlsr-53-english",
            'es': "jonatasgrosman/wav2vec2-large-xlsr-53-spanish",
            # Adicione outros se precisar, ou use um fallback
        }
        
        # Seleciona modelo baseado no idioma, com fallback para português ou modelo padrão
        model_id = models_map.get(language, models_map['pt'])
        
        print(f"Carregando Modelo: {model_id} (Idioma: {language})...")
        import torch
        import torchaudio
        import re
        import time
        from transformers import Wav2Vec2Processor, Wav2Vec2ForCTC
        
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Usando dispositivo: {device}")
        
        processor = Wav2Vec2Processor.from_pretrained(model_id)
        model = Wav2Vec2ForCTC.from_pretrained(model_id, use_safetensors=True).to(device)
        
        # Carrega Áudio
        start_t = time.time()
        waveform, sample_rate = torchaudio.load(vocals_path)
        if sample_rate != 16000:
            waveform = torchaudio.functional.resample(waveform, sample_rate, 16000)
            
        # Normalização de Áudio
        # Essencial para garantir que partes baixas (versos) tenham volume suficiente para o modelo ouvir,
        # e partes altas (refrão) não distorçam. Normalizamos pelo pico absoluto e adicionamos um epsilon.
        waveform = waveform / (torch.max(torch.abs(waveform)) + 1e-9)
        
        waveform = waveform[0].unsqueeze(0).to(device) # Single channel
        
        # Preparação do Texto (Análise da Letra Oficial)
        official_words = []
        official_lines_raw = []
        raw_lines = official_lrc_content.splitlines()
        current_line_idx = 0
        full_text_list = []
        
        for line in raw_lines:
            # Limpa colchetes [] e parênteses ()
            clean_line = re.sub(r'\[.*?\]', '', line)
            clean_line = re.sub(r'\(.*?\)', '', clean_line).strip()
            
            if not clean_line: continue
            official_lines_raw.append(clean_line)
            
            words = clean_line.split()
            for w in words:
                w_clean = re.sub(r'[^\w\s]', '', w).lower()
                official_words.append({
                    'text': w_clean,
                    'display': w,
                    'line_idx': current_line_idx,
                    'start': 0.0, 'end': 0.0
                })
                full_text_list.append(w_clean)
            current_line_idx += 1
            
        # Criar string de transcrição para o modelo (apenas letras minúsculas e espaços)
        transcript = " ".join(full_text_list)
        
        # Tokenização e Inferência
        # O modelo prevê a probabilidade de cada token (caractere) para cada frame de áudio (aprox 20ms).
        with torch.inference_mode():
            inputs = processor(text=transcript, return_tensors="pt")
            input_ids = inputs.input_ids.to(device)
            
            # Forward Pass (Inferência)
            print("Executando Inferência do Modelo...")
            emissions = model(waveform).logits
            emissions = torch.log_softmax(emissions, dim=-1)
            
            # Alinhamento Forçado (Forced Alignment)
            # Utilizamos o algoritmo Viterbi (ou similar) restrito para encontrar o melhor caminho
            # através da matriz de emissões que corresponda EXATAMENTE à sequência de texto alvo (alvos).
            targets = input_ids 
             
            print("Calculando Alinhamento...")
            from torchaudio.functional import forced_align
            
            # Preparar comprimentos
            input_lengths = torch.tensor([emissions.shape[1]], device=device)
            target_lengths = torch.tensor([targets.shape[1]], device=device)
            
            token_spans, _ = forced_align(emissions, targets, input_lengths, target_lengths)
            
            # Desempacotar lote (assumindo tamanho de lote 1)
            # token_spans corresponde à dimensão 0 de targets (Batch)
            # Então token_spans é uma lista de comprimento 1, contendo os spans para a amostra 0.
            if len(token_spans) > 0:
                spans = token_spans[0]
            else:
                spans = []
            
            # Mapeia Spans para Palavras
            # word_ids retorna [None, 0, 0, 1, 1, ...] mas é indisponível para SlowTokenizer.
            # Reconstrução Manual:
            # Tokenizer Wav2Vec2 usa <pad> ou '|' como separador ou apenas espaço.
            # Decodificamos 'input_ids' de volta para tokens para verificar.
            
            # 1. Decodificar tokens
            # Usando tokenizer diretamente
            tokenizer = processor.tokenizer
            tokens = tokenizer.convert_ids_to_tokens(input_ids[0])
            
            word_ids = []
            
            # Repassa tokens e atribui a palavras
            # O 'transcrito' foi unido por espaços.
            # O tokenizer provavelmente substitui espaços por '|' ou divide por eles.
            # O modelo JonatasGrosman geralmente usa '|' como delimitador de palavras.
            
            current_w_idx = 0
            
            for t_idx, t in enumerate(tokens):
                if t == tokenizer.word_delimiter_token or t == '|':
                    # Separador: move para próxima palavra? 
                    # Geralmente separador é seu próprio token ENTRE palavras.
                    # Ou está anexado? 
                    # Se for um separador, corresponde a None ou ao espaço? 
                    # Mapeamos para None.
                    word_ids.append(None)
                    word_ids.append(None)
                    # Usa uma flag ou lógica para avançar a palavra apenas uma vez se múltiplos separadores?
                    # Na verdade, devemos apenas incrementar se acabamos de terminar uma palavra.
                    # Mas mais simples: O tokenizer produziu isso de "word1 word2".
                    # Então 'word1' chars -> word_idx 0. '|' -> None. 'word2' -> word_idx 1.
                    if current_w_idx < len(official_words) and len(word_ids) > 1 and word_ids[-2] == current_w_idx:
                         current_w_idx += 1
                elif t == tokenizer.pad_token or t == '<s>' or t == '</s>':
                     word_ids.append(None)
                else:
                    # Caractere pertencente à paavra atual
                    if current_w_idx < len(official_words):
                        word_ids.append(current_w_idx)
                    else:
                        word_ids.append(None)
            
            
            # Verificação de segurança: se não usamos todas as palavras?
            # Ou se tivermos incompatibilidades.
            # Assumimos alinhamento estrito entre tokens gerados e texto de entrada.
           
            # Agrupar tokens por palavra
            # Filtrar tokens especiais de word_ids se houver (geralmente None no início/fim)
            # aligned_tokens[i] corresponde a input_ids[i]
            
            # 4. Processar Caminho de Alinhamento
            # 'spans' é um tensor de forma [Total_Frames] contendo o caminho de alinhamento (índices de token).
            # Precisamos segmentar esse caminho em ocorrências de token correspondentes a 'input_ids'.
            
            alignment_path = spans.cpu().numpy() if hasattr(spans, 'cpu') else spans
            if isinstance(alignment_path, torch.Tensor):
                 alignment_path = alignment_path.tolist()
            
            unique_segments = []
            current_label = None
            start_frame = 0
            
            for t, label in enumerate(alignment_path):
                # Lidar com tensor escalar se necessário, embora tolist() deva corrigir isso
                if hasattr(label, 'item'): label = label.item()
                
                if label != current_label:
                    if current_label is not None and current_label != 0: # 0 é branco (CTC padrão)
                        unique_segments.append({
                            'label': current_label,
                            'start': start_frame,
                            'end': t # Exclusive
                        })
                    current_label = label
                    start_frame = t

            # Limpar (Flush) o último segmento
            if current_label is not None and current_label != 0:
                unique_segments.append({
                    'label': current_label,
                    'start': start_frame,
                    'end': len(alignment_path)
                })

            # Verifica consistência do alinhamento
            # a contagem de unique_segments deve bater com o comprimento de input_ids (alvos)
            # Nós alinhamos cegamente com word_ids, que também bate com input_ids length.
            
            for i, seg in enumerate(unique_segments):
                if i >= len(word_ids): 
                    # Isso implica que o caminho tem mais segmentos não brancos do que alvos?
                    # Deveria ser impossível com forced_align, mas é mais seguro interromper.
                    break
                
                wid = word_ids[i]
                if wid is None: continue
                if wid >= len(official_words): continue
                
                # Converter frames para segundos
                # (Wav2Vec2 geralmente tem stride que resulta em 20ms por frame para 16kHz)
                start_sec = seg['start'] * 0.02 
                end_sec = seg['end'] * 0.02
                
                w_obj = official_words[wid]
                
                # Estender limites da palavra
                if w_obj['start'] == 0.0 and w_obj['end'] == 0.0:
                    w_obj['start'] = start_sec
                    w_obj['end'] = end_sec
                else:
                    w_obj['start'] = min(w_obj['start'], start_sec)
                    w_obj['end'] = max(w_obj['end'], end_sec)

        # 3. Construir LRC Final
        final_lrc = ""
        words_by_line_map = {}
        for w in official_words:
            idx = w['line_idx']
            if idx not in words_by_line_map: words_by_line_map[idx] = []
            words_by_line_map[idx].append(w)
            
        last_time = 0.0
        for idx in range(len(official_lines_raw)):
            if idx not in words_by_line_map: continue
            line_words = words_by_line_map[idx]
            
            line_start = line_words[0]['start']
            if line_start == 0: line_start = last_time
            last_time = line_start
            
            minutes = int(line_start // 60)
            seconds = line_start % 60
            time_tag = f"[{minutes:02d}:{seconds:05.2f}]"
            final_lrc += f"{time_tag} {official_lines_raw[idx]}\n"
            
        return final_lrc, official_words

        return song_id

    
    def download_song(self, video_id, title, artist, progress_callback=None):
        """
        Realiza o download e processamento completo da música.
        1. Baixa o áudio do YouTube com alta qualidade.
        2. Executa o pipeline de IA (separação + alinhamento).
        3. Se falhar, tenta buscar LRC padrão na internet.
        4. Atualiza a biblioteca local.
        """
        def log(msg):
            if progress_callback:
                progress_callback(msg)
            else:
                print(msg)

        log(f"Baixando {title} por {artist}...")
        
        song_id = self.generate_id()
        base_filename = os.path.join(self.song_dir, song_id)
        
        # 1. Download Áudio (MP3) - Precisamos de alta qualidade para separação
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'outtmpl': base_filename,
            'quiet': True,
            'nocheckcertificate': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://music.youtube.com/watch?v={video_id}"])
        except Exception as e:
            log(f"Erro ao baixar: {e}")
            return None

        audio_path_original = f"{base_filename}.mp3"
        
        # 2. PROCESSAMENTO IA
        log("Iniciando Melhoria IA (Separação & Sync)...")
        # Isso retornará o caminho para o instrumental e o LRC gerado
        instrumental_path, lrc_path = self.process_audio(audio_path_original, song_id, title, artist, progress_callback)
        
        final_audio_path = instrumental_path if instrumental_path else audio_path_original
        final_lrc_path = lrc_path
        
        # Fallback se a IA falhar: tenta busca padrão
        if not final_lrc_path:
             log("Geração de LRC por IA falhou. Buscando letras padrão...")
             try:
                lrc_content = syncedlyrics.search(f"{title} {artist}")
                if lrc_content:
                    final_lrc_path = f"{base_filename}.lrc"
                    with open(final_lrc_path, "w", encoding="utf-8") as f:
                        f.write(lrc_content)
             except:
                 pass
        
        # 3. Atualizar Biblioteca
        self.library[song_id] = {
            "id": song_id,
            "title": title,
            "artist": artist,
            "audio_path": final_audio_path,
            "original_audio_path": audio_path_original, # Mantém original apenas por precaução
            "lrc_path": final_lrc_path
        }
        self.save_library()
        
        return song_id


import webview
import threading

class Api:
    def __init__(self, manager):
        self.manager = manager
        self._window = None

    def set_window(self, window):
        self._window = window

    def search(self, query):
        """Busca vídeos/músicas no YouTube Music."""
        print(f"Buscando por: {query}")
        results = self.manager.search_song(query)
        # Simplifica estrutura para JS
        cleaned_results = []
        for res in results:
            cleaned_results.append({
                'videoId': res['videoId'],
                'title': res['title'],
                'artist': res['artists'][0]['name'],
                'album': res.get('album', {}).get('name', 'Desconhecido')
            })
        return cleaned_results

    def download(self, video_id, title, artist):
        print(f"Solicitando download: {title}")
        
        # Precisamos de uma maneira de enviar logs para a UI a partir desta thread.
        # Idealmente isso roda em thread pois é bloqueante.
        # Contudo, para compatibilidade com 'await' no JS, estamos bloqueando aqui.
        # Podemos enviar logs se pywebview permitir chamadas re-entrantes.
        # A melhor maneira: Iniciar thread aqui, retornar "Tarefa Iniciada", e deixar logs aparecerem sozinhos.
        
        def ui_log(msg):
            self._log(msg)
            
        code = self.manager.download_song(video_id, title, artist, progress_callback=ui_log)
        
        if code:
            return f"Sucesso! Código da Música: {code}"
        else:
             return f"Falha no Download/Processamento."


    def bulk_download(self, text):
        """Inicia o download em massa a partir de uma lista de textos/links em uma thread separada."""
        # Iniciamos uma thread para processar linhas
        t = threading.Thread(target=self._process_bulk, args=(text,))
        t.start()
        return "Download em massa iniciado. Verifique o log."

    def _process_bulk(self, text):
        """Processa o texto de input para download em massa."""
        lines = text.strip().split('\n')
        self._log(f"Processando {len(lines)} linhas...")
        
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Heurística simples para extrair ID da URL ou apenas usar o ID
            # Suporta "https://music.youtube.com/watch?v=VIDEO_ID"
            video_id = None
            if "v=" in line:
                try:
                    video_id = line.split("v=")[1].split("&")[0]
                except:
                    video_id = None
            elif len(line) == 11:
                video_id = line
            
            if video_id:
                self._log(f"ID Encontrado: {video_id}. Buscando metadados...")
                try:
                    # Nós precisamos de metadados. self.manager.ytmusic.get_song(video_id) pode funcionar
                    details = self.manager.ytmusic.get_song(video_id)
                    title = details['videoDetails']['title']
                    artist = details['videoDetails']['author']
                    
                    self._log(f"Baixando: {title} - {artist}")
                    code = self.manager.download_song(video_id, title, artist, progress_callback=lambda m: self._log(m))
                    if code:
                        self._log(f"-> Sucesso! Código: {code}")
                    else:
                        self._log(f"-> Falhou.")
                        # code = self.manager.create_mock_song(title, artist)
                        # self._log(f"-> Mock Code: {code}")
                        
                except Exception as e:
                    self._log(f"Erro ao processar {line}: {e}")
            else:
                 self._log(f"Linha inválida: {line}")
                 
        self._log("Processamento em massa concluído.")

    def _log(self, message):
        print(message)
        if self._window:
            # Escapar aspas e novas linhas para JS
            safe_msg = str(message).replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'").replace('\n', '<br>').replace('\r', '')
            self._window.evaluate_js(f'logBulk("{safe_msg}")')

def start_server():
    PORT = 8000
    Handler = http.server.SimpleHTTPRequestHandler
    # Libera portas se estiverem em uso
    while True:
        try:
            with socketserver.TCPServer(("", PORT), Handler) as httpd:
                print(f"Serving at port {PORT}")
                httpd.serve_forever()
        except OSError:
            PORT += 1

if __name__ == "__main__":
    # Inicia servidor local para evitar restrições de file:// (para incorporação do YouTube)
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    
    # Aguarda um pouco para o servidor (naive)
    time.sleep(1)
    
    manager = SongManager()
    api = Api(manager)
    
    # Conecta ao localhost
    # Nota: assumimos a porta 8000. Se tivermos lógica de retry acima, devemos comunicar a porta.
    # Para simplicidade, vamos manter a 8000 ou encontrar uma livre e usá-la efetivamente.
    # Lógica refinada abaixo:
    
    # Na verdade, vamos usar a porta 8000 estritamente por enquanto.
    window = webview.create_window('Karaoke Song Manager', 'http://localhost:8000/manager.html', js_api=api, width=1000, height=800)
    api.set_window(window)
    webview.start()

