"""
Model Manager for AI Lightning Node Client.

Gestisce i modelli disponibili sul nodo e la sincronizzazione con il server.
"""
import os
import json
import shutil
import hashlib
import logging
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime

logger = logging.getLogger('ModelManager')


@dataclass
class ModelInfo:
    """Informazioni su un modello GGUF (locale o HuggingFace)."""
    id: str  # Hash del file o ID HuggingFace
    name: str  # Nome leggibile
    filename: str  # Nome file (per locali) o repo:quant (per HF)
    filepath: str  # Path completo (vuoto per HF)
    size_bytes: int
    size_gb: float
    parameters: str  # Es: "7B", "13B", "70B"
    quantization: str  # Es: "Q4_K_M", "Q8_0"
    context_length: int  # Default 4096
    architecture: str  # Es: "llama", "mistral", "phi"
    created_at: str
    
    # Requisiti
    min_vram_mb: int
    recommended_vram_mb: int
    
    # Stato
    enabled: bool = True
    
    # HuggingFace support
    hf_repo: str = ""  # Es: "bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M"
    is_huggingface: bool = False
    
    # Usage tracking
    last_used: str = ""  # ISO timestamp dell'ultimo utilizzo
    use_count: int = 0  # Numero di utilizzi


# Mappatura parametri -> VRAM necessaria (approssimativa per Q4)
VRAM_REQUIREMENTS = {
    '1B': {'min': 1000, 'rec': 2000},
    '3B': {'min': 2500, 'rec': 4000},
    '7B': {'min': 4000, 'rec': 6000},
    '8B': {'min': 5000, 'rec': 8000},
    '13B': {'min': 8000, 'rec': 12000},
    '14B': {'min': 9000, 'rec': 14000},
    '32B': {'min': 20000, 'rec': 32000},
    '34B': {'min': 22000, 'rec': 36000},
    '70B': {'min': 40000, 'rec': 48000},
    '72B': {'min': 42000, 'rec': 50000},
}


def parse_model_name(filename: str) -> Dict:
    """
    Estrae informazioni dal nome del file GGUF.
    
    Formati comuni:
    - llama-2-7b-chat.Q4_K_M.gguf
    - mistral-7b-instruct-v0.2.Q4_K_S.gguf
    - phi-2.Q8_0.gguf
    - deepseek-coder-6.7b-instruct.Q4_K_M.gguf
    """
    info = {
        'name': filename.replace('.gguf', ''),
        'parameters': 'Unknown',
        'quantization': 'Unknown',
        'architecture': 'unknown'
    }
    
    name_lower = filename.lower()
    
    # Rileva architettura
    architectures = [
        'llama', 'mistral', 'mixtral', 'phi', 'qwen', 'gemma', 
        'deepseek', 'codellama', 'starcoder', 'falcon', 'yi',
        'vicuna', 'wizard', 'orca', 'neural', 'openchat'
    ]
    for arch in architectures:
        if arch in name_lower:
            info['architecture'] = arch
            break
    
    # Rileva parametri
    import re
    # Cerca pattern come 7b, 7B, 13b, 70b, 6.7b, etc.
    param_match = re.search(r'(\d+\.?\d*)\s*[bB]', filename)
    if param_match:
        param_num = float(param_match.group(1))
        if param_num < 1:
            info['parameters'] = f"{int(param_num * 1000)}M"
        else:
            info['parameters'] = f"{int(param_num)}B" if param_num == int(param_num) else f"{param_num}B"
    
    # Rileva quantizzazione
    quant_patterns = [
        r'[._-](Q\d+_K_[SMLX]+)', r'[._-](Q\d+_K)', r'[._-](Q\d+_\d+)',
        r'[._-](Q\d+)', r'[._-](F16)', r'[._-](F32)', r'[._-](BF16)',
        r'[._-](IQ\d+_[SMLX]+)', r'[._-](IQ\d+)'
    ]
    for pattern in quant_patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            info['quantization'] = match.group(1).upper()
            break
    
    # Crea nome leggibile
    name_parts = []
    if info['architecture'] != 'unknown':
        name_parts.append(info['architecture'].capitalize())
    if info['parameters'] != 'Unknown':
        name_parts.append(info['parameters'])
    if info['quantization'] != 'Unknown':
        name_parts.append(info['quantization'])
    
    if name_parts:
        info['name'] = ' '.join(name_parts)
    
    return info


def calculate_file_hash(filepath: str, chunk_size: int = 8192) -> str:
    """Calculate MD5 hash of file (first 10MB for speed)."""
    hasher = hashlib.md5()
    max_bytes = 10 * 1024 * 1024  # 10MB
    bytes_read = 0
    
    with open(filepath, 'rb') as f:
        while bytes_read < max_bytes:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
            bytes_read += len(chunk)
    
    # Add size for uniqueness
    size = os.path.getsize(filepath)
    hasher.update(str(size).encode())
    
    return hasher.hexdigest()[:16]


def get_vram_requirements(parameters: str) -> Dict[str, int]:
    """Ottieni requisiti VRAM in base ai parametri."""
    # Normalizza
    param_upper = parameters.upper().replace(' ', '')
    
    # Cerca match esatto
    if param_upper in VRAM_REQUIREMENTS:
        return VRAM_REQUIREMENTS[param_upper]
    
    # Cerca match parziale
    for key, values in VRAM_REQUIREMENTS.items():
        if key in param_upper or param_upper in key:
            return values
    
    # Stima basata sul numero
    import re
    match = re.search(r'(\d+\.?\d*)', param_upper)
    if match:
        num = float(match.group(1))
        # ~600MB per 1B parametri in Q4
        estimated = int(num * 600)
        return {'min': estimated, 'rec': int(estimated * 1.5)}
    
    return {'min': 4000, 'rec': 8000}  # Default


class ModelManager:
    """Gestisce i modelli disponibili sul nodo."""
    
    # Soglia spazio disco critico (5GB)
    CRITICAL_DISK_SPACE_GB = 5.0
    # Soglia spazio disco warning (10GB)
    WARNING_DISK_SPACE_GB = 10.0
    
    def __init__(self, models_dir: str = None):
        self.models_dir = models_dir or os.path.join(os.getcwd(), 'models')
        self.models: Dict[str, ModelInfo] = {}
        self.config_file = os.path.join(self.models_dir, 'models_config.json')
        
        # Crea directory se non esiste
        Path(self.models_dir).mkdir(parents=True, exist_ok=True)
        
        # Carica configurazione
        self.load_config()
    
    def get_disk_space(self) -> Tuple[float, float, float]:
        """
        Ottieni informazioni sullo spazio disco.
        
        Returns:
            Tuple[total_gb, used_gb, free_gb]
        """
        try:
            total, used, free = shutil.disk_usage(self.models_dir)
            return (
                total / (1024 ** 3),
                used / (1024 ** 3),
                free / (1024 ** 3)
            )
        except Exception as e:
            logger.error(f"Error getting disk space: {e}")
            return (0.0, 0.0, 0.0)
    
    def get_disk_space_status(self) -> Dict:
        """
        Ottieni stato spazio disco con warning/critical status.
        
        Returns:
            Dict con total, used, free (in GB) e status ('ok', 'warning', 'critical')
        """
        total, used, free = self.get_disk_space()
        
        if free < self.CRITICAL_DISK_SPACE_GB:
            status = 'critical'
        elif free < self.WARNING_DISK_SPACE_GB:
            status = 'warning'
        else:
            status = 'ok'
        
        return {
            'total_gb': round(total, 2),
            'used_gb': round(used, 2),
            'free_gb': round(free, 2),
            'status': status,
            'models_size_gb': round(self.get_models_total_size() / (1024 ** 3), 2)
        }
    
    def get_models_total_size(self) -> int:
        """Calculate total size of local models in bytes."""
        total = 0
        for model in self.models.values():
            if not model.is_huggingface and model.filepath and os.path.exists(model.filepath):
                total += model.size_bytes
        return total
    
    def get_unused_models(self, days_threshold: int = 30) -> List[ModelInfo]:
        """
        Get list of models not used for more than X days.
        
        Args:
            days_threshold: Number of days of inactivity
            
        Returns:
            List of models sorted by last use (oldest first)
        """
        from datetime import timedelta
        threshold_date = datetime.now() - timedelta(days=days_threshold)
        
        unused = []
        for model in self.models.values():
            # Considera solo modelli locali con file esistente
            if model.is_huggingface:
                continue
            if not model.filepath or not os.path.exists(model.filepath):
                continue
            
            # Controlla ultimo utilizzo
            if model.last_used:
                try:
                    last_used_dt = datetime.fromisoformat(model.last_used)
                    if last_used_dt < threshold_date:
                        unused.append(model)
                except:
                    unused.append(model)  # Data invalida = mai usato
            else:
                unused.append(model)  # Mai usato
        
        # Sort by last use (oldest first)
        unused.sort(key=lambda m: m.last_used or '1970-01-01')
        return unused
    
    def delete_model(self, model_id: str, delete_file: bool = True) -> bool:
        """
        Elimina un modello.
        
        Args:
            model_id: ID del modello
            delete_file: Se True, elimina anche il file fisico
            
        Returns:
            True se eliminato con successo
        """
        if model_id not in self.models:
            return False
        
        model = self.models[model_id]
        
        # Elimina file se richiesto e esiste
        if delete_file and not model.is_huggingface and model.filepath:
            try:
                if os.path.exists(model.filepath):
                    os.remove(model.filepath)
                    logger.info(f"Deleted model file: {model.filepath}")
            except Exception as e:
                logger.error(f"Error deleting model file: {e}")
                return False
        
        # Rimuovi dalla lista
        del self.models[model_id]
        self.save_config()
        
        logger.info(f"Model {model.name} removed")
        return True
    
    def cleanup_old_models(self, target_free_gb: float = None) -> List[str]:
        """
        Pulisce modelli vecchi/non usati per liberare spazio.
        
        Args:
            target_free_gb: Spazio libero target (default: WARNING_DISK_SPACE_GB)
            
        Returns:
            Lista nomi dei modelli eliminati
        """
        if target_free_gb is None:
            target_free_gb = self.WARNING_DISK_SPACE_GB
        
        deleted = []
        _, _, free = self.get_disk_space()
        
        # Ottieni modelli non usati
        unused = self.get_unused_models(days_threshold=30)
        
        for model in unused:
            if free >= target_free_gb:
                break
            
            size_gb = model.size_bytes / (1024 ** 3)
            if self.delete_model(model.id, delete_file=True):
                deleted.append(model.name)
                free += size_gb
                logger.info(f"Cleaned up model {model.name}, freed {size_gb:.2f} GB")
        
        return deleted
    
    def mark_model_used(self, model_id: str):
        """Mark a model as used (update timestamp and counter)."""
        if model_id in self.models:
            self.models[model_id].last_used = datetime.now().isoformat()
            self.models[model_id].use_count += 1
            self.save_config()
    
    def load_config(self):
        """Load saved model configuration."""
        print(f"[DEBUG ModelManager] Looking for config at: {self.config_file}")
        print(f"[DEBUG ModelManager] Config exists: {os.path.exists(self.config_file)}")
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    for model_id, model_data in data.get('models', {}).items():
                        self.models[model_id] = ModelInfo(**model_data)
                print(f"[DEBUG ModelManager] Loaded {len(self.models)} models from config")
                logger.info(f"Loaded {len(self.models)} models from config")
            except Exception as e:
                print(f"[DEBUG ModelManager] Error loading config: {e}")
                logger.error(f"Error loading config: {e}")
        else:
            print(f"[DEBUG ModelManager] Config file not found")
    
    def save_config(self):
        """Save model configuration."""
        try:
            data = {
                'models': {k: asdict(v) for k, v in self.models.items()},
                'updated_at': datetime.now().isoformat()
            }
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved config with {len(self.models)} models")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    def scan_models(self) -> List[ModelInfo]:
        """Scan directory for GGUF files."""
        found_models = []
        
        if not os.path.exists(self.models_dir):
            logger.warning(f"Models directory does not exist: {self.models_dir}")
            return found_models
        
        for filename in os.listdir(self.models_dir):
            if filename.lower().endswith('.gguf'):
                # Skip mmproj/CLIP files - these are multimodal projectors, not main models
                if 'mmproj' in filename.lower() or 'clip' in filename.lower():
                    logger.info(f"Skipping mmproj/CLIP file (not a main model): {filename}")
                    continue
                
                filepath = os.path.join(self.models_dir, filename)
                
                try:
                    # Calculate hash
                    model_id = calculate_file_hash(filepath)
                    
                    # If already present, only update the path
                    if model_id in self.models:
                        self.models[model_id].filepath = filepath
                        found_models.append(self.models[model_id])
                        continue
                    
                    # Parse nome file
                    parsed = parse_model_name(filename)
                    
                    # Ottieni requisiti VRAM
                    vram_req = get_vram_requirements(parsed['parameters'])
                    
                    # Crea ModelInfo
                    size_bytes = os.path.getsize(filepath)
                    model = ModelInfo(
                        id=model_id,
                        name=parsed['name'],
                        filename=filename,
                        filepath=filepath,
                        size_bytes=size_bytes,
                        size_gb=round(size_bytes / (1024**3), 2),
                        parameters=parsed['parameters'],
                        quantization=parsed['quantization'],
                        context_length=4096,  # Default
                        architecture=parsed['architecture'],
                        created_at=datetime.fromtimestamp(
                            os.path.getctime(filepath)
                        ).isoformat(),
                        min_vram_mb=vram_req['min'],
                        recommended_vram_mb=vram_req['rec'],
                        enabled=True
                    )
                    
                    self.models[model_id] = model
                    found_models.append(model)
                    logger.info(f"Found model: {model.name} ({model.size_gb} GB)")
                    
                except Exception as e:
                    logger.error(f"Error scanning {filename}: {e}")
        
        # Remove models no longer present
        to_remove = []
        for model_id, model in self.models.items():
            if not os.path.exists(model.filepath):
                to_remove.append(model_id)
        
        for model_id in to_remove:
            logger.info(f"Removing missing model: {self.models[model_id].name}")
            del self.models[model_id]
        
        # Salva configurazione
        self.save_config()
        
        return list(self.models.values())
    
    def get_enabled_models(self) -> List[ModelInfo]:
        """Restituisce solo i modelli abilitati."""
        return [m for m in self.models.values() if m.enabled]
    
    def set_model_enabled(self, model_id: str, enabled: bool):
        """Abilita/disabilita un modello."""
        if model_id in self.models:
            self.models[model_id].enabled = enabled
            self.save_config()
            return True
        return False
    
    def set_model_context_length(self, model_id: str, context_length: int):
        """Imposta context length per un modello."""
        if model_id in self.models:
            self.models[model_id].context_length = context_length
            self.save_config()
            return True
        return False
    
    def get_models_for_server(self) -> List[Dict]:
        """
        Prepara lista modelli da inviare al server.
        Include solo i dati necessari.
        """
        models = []
        for model in self.get_enabled_models():
            # Use filename as name for display (without .gguf extension)
            display_name = model.filename.replace('.gguf', '').replace('.GGUF', '') if model.filename else model.name
            model_data = {
                'id': model.id,
                'name': display_name,
                'parameters': model.parameters,
                'quantization': model.quantization,
                'context_length': model.context_length,
                'architecture': model.architecture,
                'size_gb': model.size_gb,
                'min_vram_mb': model.min_vram_mb,
                'recommended_vram_mb': model.recommended_vram_mb,
                'is_huggingface': model.is_huggingface
            }
            # Aggiungi info HuggingFace se presente
            if model.hf_repo:
                model_data['hf_repo'] = model.hf_repo
            if model.filename:
                model_data['filename'] = model.filename
            models.append(model_data)
        return models
    
    def get_model_by_id(self, model_id: str) -> Optional[ModelInfo]:
        """Ottieni modello per ID."""
        return self.models.get(model_id)
    
    def get_model_by_name(self, name: str) -> Optional[ModelInfo]:
        """Trova modello per nome (parziale)."""
        name_lower = name.lower()
        for model in self.models.values():
            if name_lower in model.name.lower() or name_lower in model.filename.lower():
                return model
            # Cerca anche per hf_repo
            if model.hf_repo and name_lower in model.hf_repo.lower():
                return model
        return None
    
    def add_huggingface_model(self, hf_repo: str, context_length: int = 4096) -> Optional[ModelInfo]:
        """
        Aggiunge un modello HuggingFace.
        
        Args:
            hf_repo: Repository HuggingFace nel formato "owner/repo:quantization"
                    Es: "bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M"
            context_length: Context length da usare
            
        Returns:
            ModelInfo creato o None in caso di errore
        """
        try:
            # Parse del repo HuggingFace
            parsed = parse_huggingface_repo(hf_repo)
            
            # Crea ID unico basato sul repo
            import hashlib
            model_id = hashlib.md5(hf_repo.encode()).hexdigest()[:16]
            
            # Check if already exists
            if model_id in self.models:
                logger.info(f"Model {hf_repo} already exists")
                return self.models[model_id]
            
            # Ottieni requisiti VRAM
            vram_req = get_vram_requirements(parsed['parameters'])
            
            # Stima dimensione (approssimativa basata sui parametri)
            param_num = 7  # default
            import re
            match = re.search(r'(\d+\.?\d*)', parsed['parameters'])
            if match:
                param_num = float(match.group(1))
            
            # Stima: ~0.5GB per 1B parametri in Q4
            estimated_size_gb = round(param_num * 0.5, 2)
            
            model = ModelInfo(
                id=model_id,
                name=parsed['name'],
                filename=hf_repo,  # Usa repo come "filename"
                filepath="",  # Vuoto per HF
                size_bytes=int(estimated_size_gb * 1024**3),
                size_gb=estimated_size_gb,
                parameters=parsed['parameters'],
                quantization=parsed['quantization'],
                context_length=context_length,
                architecture=parsed['architecture'],
                created_at=datetime.now().isoformat(),
                min_vram_mb=vram_req['min'],
                recommended_vram_mb=vram_req['rec'],
                enabled=True,
                hf_repo=hf_repo,
                is_huggingface=True
            )
            
            self.models[model_id] = model
            self.save_config()
            logger.info(f"Added HuggingFace model: {model.name} ({hf_repo})")
            
            return model
            
        except Exception as e:
            logger.error(f"Error adding HuggingFace model {hf_repo}: {e}")
            return None
    
    def remove_model(self, model_id: str) -> bool:
        """Rimuove un modello."""
        if model_id in self.models:
            model = self.models[model_id]
            del self.models[model_id]
            self.save_config()
            logger.info(f"Removed model: {model.name}")
            return True
        return False


def parse_huggingface_repo(hf_repo: str) -> Dict:
    """
    Estrae informazioni da un repository HuggingFace.
    
    Formati supportati:
    - "owner/repo:quantization" (es: "bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M")
    - "owner/repo" (senza quantizzazione specifica)
    """
    info = {
        'name': hf_repo,
        'parameters': 'Unknown',
        'quantization': 'Unknown',
        'architecture': 'unknown',
        'owner': '',
        'repo': ''
    }
    
    # Split owner/repo:quant
    parts = hf_repo.split(':')
    repo_part = parts[0]
    quant_part = parts[1] if len(parts) > 1 else ''
    
    # Split owner/repo
    if '/' in repo_part:
        owner, repo = repo_part.split('/', 1)
        info['owner'] = owner
        info['repo'] = repo
    else:
        info['repo'] = repo_part
    
    repo_lower = repo_part.lower()
    
    # Rileva architettura
    architectures = [
        'llama', 'mistral', 'mixtral', 'phi', 'qwen', 'gemma', 
        'deepseek', 'codellama', 'starcoder', 'falcon', 'yi',
        'vicuna', 'wizard', 'orca', 'neural', 'openchat', 'smollm'
    ]
    for arch in architectures:
        if arch in repo_lower:
            info['architecture'] = arch
            break
    
    # Rileva parametri
    import re
    param_match = re.search(r'(\d+\.?\d*)\s*[bB]', repo_part)
    if param_match:
        param_num = float(param_match.group(1))
        if param_num < 1:
            info['parameters'] = f"{int(param_num * 1000)}M"
        else:
            info['parameters'] = f"{int(param_num)}B" if param_num == int(param_num) else f"{param_num}B"
    
    # Rileva quantizzazione
    if quant_part:
        info['quantization'] = quant_part.upper()
    else:
        # Cerca nella stringa
        quant_patterns = [
            r'[._-](Q\d+_K_[SMLX]+)', r'[._-](Q\d+_K)', r'[._-](Q\d+_\d+)',
            r'[._-](Q\d+)', r'[._-](F16)', r'[._-](F32)', r'[._-](BF16)',
            r'[._-](IQ\d+_[SMLX]+)', r'[._-](IQ\d+)'
        ]
        for pattern in quant_patterns:
            match = re.search(pattern, repo_part, re.IGNORECASE)
            if match:
                info['quantization'] = match.group(1).upper()
                break
    
    # Crea nome leggibile
    name_parts = []
    if info['architecture'] != 'unknown':
        name_parts.append(info['architecture'].capitalize())
    if info['parameters'] != 'Unknown':
        name_parts.append(info['parameters'])
    if info['quantization'] != 'Unknown':
        name_parts.append(info['quantization'])
    
    if name_parts:
        info['name'] = ' '.join(name_parts)
    else:
        # Usa repo name
        info['name'] = info['repo'].replace('-GGUF', '').replace('-gguf', '')
    
    return info


class ModelSyncClient:
    """Client for model synchronization with central server."""
    
    def __init__(self, server_url: str, node_token: str = None):
        self.server_url = server_url.rstrip('/')
        self.node_token = node_token
    
    def sync_models(self, node_id: str, hardware_info: Dict, models: List[Dict]) -> Dict:
        """
        Synchronize models with the server.
        
        Sends:
        - Node hardware info
        - Available models list
        
        Receives:
        - Registration confirmation
        - Possibly models requested by the network
        """
        try:
            payload = {
                'node_id': node_id,
                'hardware': hardware_info,
                'models': models,
                'timestamp': datetime.now().isoformat()
            }
            
            headers = {'Content-Type': 'application/json'}
            if self.node_token:
                headers['Authorization'] = f'Bearer {self.node_token}'
            
            response = requests.post(
                f'{self.server_url}/api/nodes/sync',
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Sync failed: {response.status_code} - {response.text}")
                return {'error': response.text}
                
        except Exception as e:
            logger.error(f"Sync error: {e}")
            return {'error': str(e)}
    
    def get_network_models(self) -> List[Dict]:
        """Ottieni lista di tutti i modelli disponibili nella rete."""
        try:
            response = requests.get(
                f'{self.server_url}/api/models/available',
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json().get('models', [])
            return []
            
        except Exception as e:
            logger.error(f"Error getting network models: {e}")
            return []


if __name__ == '__main__':
    # Test
    logging.basicConfig(level=logging.DEBUG)
    
    manager = ModelManager('./test_models')
    models = manager.scan_models()
    
    print(f"\nFound {len(models)} models:")
    for model in models:
        print(f"  - {model.name}")
        print(f"    File: {model.filename}")
        print(f"    Size: {model.size_gb} GB")
        print(f"    Params: {model.parameters}, Quant: {model.quantization}")
        print(f"    VRAM: {model.min_vram_mb}MB min, {model.recommended_vram_mb}MB rec")
        print()
