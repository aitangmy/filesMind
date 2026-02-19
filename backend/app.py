"""
FilesMind 服务协议
支持异步任务、进度追踪和文件历史记录
"""
import os
import uuid
import asyncio
import logging
import hashlib
import json
from datetime import datetime, timezone
import re
import threading
from copy import deepcopy

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("FilesMind")


from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse
import shutil
from cryptography.fernet import Fernet, InvalidToken

# 导入扩展模块
from parser_service import process_pdf_safely, get_parser_runtime_config, update_parser_runtime_config
from cognitive_engine import generate_mindmap_structure, update_client_config, test_connection, set_model, set_account_type
from xmind_exporter import generate_xmind_content



# ==================== 辅助函数 ====================
def count_headers(text: str) -> Dict[str, int]:
    """统计 Markdown 文本中各级标题数量"""
    counts = {"h1": 0, "h2": 0, "h3": 0, "h4": 0, "h5": 0, "h6": 0, "total": 0}
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#'):
            match = re.match(r'^(#{1,6})\s', stripped)
            if match:
                level = len(match.group(1))
                counts[f"h{level}"] += 1
                counts["total"] += 1
    return counts

# ==================== 智能分块函数 ====================
def parse_markdown_chunks(md_content: str) -> List[Dict]:
    """
    智能分块：基于大小和结构的动态分块
    目标：将文档合并为较大的语义块（约 15k 字符），减少碎片化，提升 AI 上下文理解能力。
    
    关键修复：
    1. 引入标题栈 (Header Stack) 维护层级上下文
    2. 返回结构改为 List[Dict] 以携带 context
    """
    if not md_content or not md_content.strip():
        return []

    TARGET_CHUNK_SIZE = 6000
    lines = md_content.split('\n')
    
    chunks = []
    current_chunk_lines = []
    current_size = 0
    
    # 核心：维护标题栈 [{'level': 1, 'text': 'Chapter 1'}, ...]
    header_stack = [] 
    header_pattern = re.compile(r'^(#{1,6})\s+(.*)')

    for line in lines:
        stripped = line.strip()
        header_match = header_pattern.match(stripped)
        
        # --- 1. 维护上下文栈 ---
        if header_match:
            level = len(header_match.group(1))
            text = header_match.group(2).strip()
            
            # 弹出所有级别 >= 当前级别的标题（保持层级树的正确性）
            while header_stack and header_stack[-1]['level'] >= level:
                header_stack.pop()
            
            header_stack.append({'level': level, 'text': text})

        # --- 2. 决定是否切分 ---
        line_len = len(line) + 1 # +1 for newline
        
        # 触发切分的条件：
        # 1. 大小超标 
        # 2. 且当前行是标题（尽量在章节处切断）
        # 3. 或者当前块实在太大了（超过 2 倍目标），强制切分
        flag_split_at_header = (current_size >= TARGET_CHUNK_SIZE and header_match)
        flag_force_split = (current_size >= TARGET_CHUNK_SIZE * 2)

        if flag_split_at_header or flag_force_split:
            if current_chunk_lines:
                # 生成当前块的 Context String
                # 策略调整：
                # 如果是 Header 触发的切分，stack 包含了新 Header，Context 应为新 Header 的父级 (stack[:-1])
                # 如果是强制切分，stack 是当前上下文，Context 应为完整 stack (stack[:]) 以保留当前位置
                
                # 用户原始逻辑使用 stack[:-1]，我们在此微调以增强鲁棒性：
                # 但遵循用户的 Draft 代码为主，此处稍微优化 'split reason' 判断
                
                use_parent_context = True if header_match else False
                
                eff_stack = header_stack[:-1] if (use_parent_context and len(header_stack) > 1) else header_stack
                # 注意 user code: context_str = " > ".join([h['text'] for h in header_stack[:-1]]) if len(header_stack) > 1 else ""
                # if not context_str...
                
                # 采用用户提供的稳健逻辑 (Original User Code Path)
                # 使用切分时刻的 stack (包含了新头)。
                # 之前块的 Context: 理论上是新头之前的状态。
                # 但如果我们已经 update 了 stack...
                # User Code update stack BEFORE split check.
                # So header_stack includes the NEW header.
                # The Previous Chunk (which we are saving now) ENDS right before this new header.
                # So its context is indeed best described by the PARENT of the new header (if siblings).
                # Example: Old=1.1, New=1.2. Stack=[1, 1.2]. Context=[1]. Chunk 1.1 -> under 1. Correct.
                
                context_source = header_stack[:-1] if len(header_stack) > 1 else []
                context_str = " > ".join([h['text'] for h in context_source])
                
                if not context_str and header_stack:
                     # 顶层或者是只有一级
                     # 注意：如果是 [H1, H2]，source=[H1]，context="H1"
                     # 如果是 [H1]，source=[]，context="" -> Fallback to H1
                     context_str = header_stack[0]['text']

                # 计算 context 深度和建议的起始标题级别
                context_depth = len(context_source) if context_source else (1 if header_stack else 0)
                expected_start_level = min(context_depth + 2, 6)  # H1=root, context占用后续级别

                chunks.append({
                    "content": '\n'.join(current_chunk_lines),
                    "context": context_str,
                    "context_depth": context_depth,
                    "expected_start_level": expected_start_level
                })
                current_chunk_lines = []
                current_size = 0
        
        current_chunk_lines.append(line)
        current_size += line_len

    # 处理最后一个块
    if current_chunk_lines:
        context_str = " > ".join([h['text'] for h in header_stack])
        context_depth = len(header_stack)
        expected_start_level = min(context_depth + 2, 6)
        chunks.append({
            "content": '\n'.join(current_chunk_lines),
            "context": context_str,
            "context_depth": context_depth,
            "expected_start_level": expected_start_level
        })

    # 标题统计日志
    total_headers = count_headers(md_content)
    logger.info(f"智能分块完成，共 {len(chunks)} 个章节 (Target: {TARGET_CHUNK_SIZE} chars)")
    logger.info(f"原文标题统计: H1={total_headers['h1']}, H2={total_headers['h2']}, H3={total_headers['h3']}, H4={total_headers['h4']}, H5={total_headers['h5']}, H6={total_headers['h6']}, 总计={total_headers['total']}")
    for i, chunk in enumerate(chunks):
        chunk_headers = count_headers(chunk.get('content', ''))
        ctx = chunk.get('context', 'N/A')
        esl = chunk.get('expected_start_level', '?')
        if chunk_headers['total'] > 0:
            logger.info(f"Chunk {i}: {chunk_headers['total']} 个标题 (H2={chunk_headers['h2']}, H3={chunk_headers['h3']}, H4={chunk_headers['h4']}) | Context=[{ctx[:40]}] | StartLevel=H{esl}")
    return chunks


def fallback_chunking(md_content: str, chunk_size: int = 15000) -> list:
    """备用分块方案：按字符长度均分，尽量在段落处分割"""
    if len(md_content) <= chunk_size:
        return [md_content] if md_content.strip() else []

    chunks = []
    # 按双换行（段落）分割
    paragraphs = md_content.split('\n\n')
    current_chunk = ""

    for para in paragraphs:
        # 如果加上这段会超长
        if len(current_chunk) + len(para) > chunk_size:
            # 如果当前块不为空，先保存当前块
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
                current_chunk = ""

            # 如果单个段落本身就超长，强制切分
            if len(para) > chunk_size:
                # 递归切分超长段落
                sub_chunks = [para[i:i+chunk_size] for i in range(0, len(para), chunk_size)]
                chunks.extend(sub_chunks)
            else:
                current_chunk = para + "\n\n"
        else:
            current_chunk += para + "\n\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


app = FastAPI()

# ==================== 配置管理 ====================
# 使用绝对路径，确保在任何目录启动都能找到配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "data", "config.json")
CONFIG_KEY_FILE = os.path.join(BASE_DIR, "data", "config.key")
MASKED_SECRET = "***"
CONFIG_SCHEMA_VERSION = 3
ENCRYPTION_PREFIX = "enc:v1:"
_config_cipher: Optional[Fernet] = None

DEFAULT_PROVIDER_PRESETS = {
    "minimax": {"base_url": "https://api.minimaxi.com/v1", "model": "MiniMax-M2.5"},
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
    "openai": {"base_url": "https://api.openai.com", "model": "gpt-4o-mini"},
    "anthropic": {"base_url": "https://api.anthropic.com", "model": "claude-3-5-sonnet-20241022"},
    "moonshot": {"base_url": "https://api.moonshot.cn", "model": "moonshot-v1-8k-vision-preview"},
    "dashscope": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "qwen2.5:7b"},
    "custom": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
}


class ConfigValidationError(ValueError):
    def __init__(self, code: str, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def to_detail(self) -> Dict[str, Any]:
        detail = {"code": self.code, "message": self.message}
        if self.field:
            detail["field"] = self.field
        return detail


class ProfilePayload(BaseModel):
    id: str
    name: str
    provider: str = "custom"
    base_url: str
    model: str
    api_key: str = ""
    account_type: str = "free"
    manual_models: List[str] = Field(default_factory=list)


class ParserSettingsPayload(BaseModel):
    parser_backend: str = "docling"
    hybrid_noise_threshold: float = 0.20
    hybrid_docling_skip_score: float = 70.0
    hybrid_switch_min_delta: float = 2.0
    hybrid_marker_min_length: int = 200
    marker_prefer_api: bool = False


class ConfigStorePayload(BaseModel):
    active_profile_id: str
    profiles: List[ProfilePayload] = Field(default_factory=list)
    parser: ParserSettingsPayload = Field(default_factory=ParserSettingsPayload)


class ProfileView(BaseModel):
    id: str
    name: str
    provider: str
    base_url: str
    model: str
    api_key: str
    has_api_key: bool
    account_type: str
    manual_models: List[str] = Field(default_factory=list)


class ConfigStoreView(BaseModel):
    schema_version: int
    active_profile_id: str
    profiles: List[ProfileView] = Field(default_factory=list)
    parser: ParserSettingsPayload = Field(default_factory=ParserSettingsPayload)


class ModelListRequest(BaseModel):
    profile: ProfilePayload


class ConfigImportPayload(BaseModel):
    active_profile_id: str
    profiles: List[Dict[str, Any]] = Field(default_factory=list)
    parser: Optional[Dict[str, Any]] = None


def _is_ollama_url(base_url: str) -> bool:
    lowered = (base_url or "").lower()
    return "ollama" in lowered or "11434" in lowered


def _default_profile() -> Dict[str, Any]:
    preset = DEFAULT_PROVIDER_PRESETS["minimax"]
    return {
        "id": str(uuid.uuid4()),
        "name": "Default",
        "provider": "minimax",
        "base_url": preset["base_url"],
        "model": preset["model"],
        "api_key": "",
        "account_type": "free",
        "manual_models": [],
    }


def _default_parser_config() -> Dict[str, Any]:
    runtime = get_parser_runtime_config()
    return {
        "parser_backend": str(runtime.get("parser_backend", "docling")),
        "hybrid_noise_threshold": float(runtime.get("hybrid_noise_threshold", 0.20)),
        "hybrid_docling_skip_score": float(runtime.get("hybrid_docling_skip_score", 70.0)),
        "hybrid_switch_min_delta": float(runtime.get("hybrid_switch_min_delta", 2.0)),
        "hybrid_marker_min_length": int(runtime.get("hybrid_marker_min_length", 200)),
        "marker_prefer_api": bool(runtime.get("marker_prefer_api", False)),
    }


def _normalize_models(models: Any) -> List[str]:
    if models is None:
        return []
    if isinstance(models, str):
        items = re.split(r"[,;\n]", models)
    elif isinstance(models, list):
        items = models
    else:
        return []

    normalized = []
    seen = set()
    for raw in items:
        value = str(raw).strip()
        if not value:
            continue
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized[:100]


def _ensure_config_key() -> bytes:
    os.makedirs(os.path.dirname(CONFIG_KEY_FILE), exist_ok=True)
    if os.path.exists(CONFIG_KEY_FILE):
        with open(CONFIG_KEY_FILE, "rb") as f:
            key = f.read().strip()
        if key:
            return key

    key = Fernet.generate_key()
    with open(CONFIG_KEY_FILE, "wb") as f:
        f.write(key)
    try:
        os.chmod(CONFIG_KEY_FILE, 0o600)
    except Exception:
        # Windows on some environments does not fully support chmod semantics.
        pass
    return key


def _get_config_cipher() -> Fernet:
    global _config_cipher
    if _config_cipher is None:
        _config_cipher = Fernet(_ensure_config_key())
    return _config_cipher


def _encrypt_secret(secret: str) -> str:
    if not secret:
        return ""
    if secret.startswith(ENCRYPTION_PREFIX):
        return secret
    cipher = _get_config_cipher()
    token = cipher.encrypt(secret.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTION_PREFIX}{token}"


def _decrypt_secret(secret: str) -> str:
    if not secret:
        return ""
    if not secret.startswith(ENCRYPTION_PREFIX):
        return secret
    cipher = _get_config_cipher()
    token = secret[len(ENCRYPTION_PREFIX):]
    try:
        return cipher.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ConfigValidationError("INVALID_ENCRYPTED_KEY", "密钥解密失败，配置文件可能已损坏")


def _decrypt_store_inplace(raw: Dict[str, Any]):
    if "profiles" in raw and isinstance(raw.get("profiles"), list):
        for profile in raw["profiles"]:
            if isinstance(profile, dict) and "api_key" in profile:
                profile["api_key"] = _decrypt_secret(str(profile.get("api_key", "")))
    elif "api_key" in raw:
        # legacy 单配置
        raw["api_key"] = _decrypt_secret(str(raw.get("api_key", "")))


def _encrypt_store_for_disk(config_store: Dict[str, Any]) -> Dict[str, Any]:
    cloned = deepcopy(config_store)
    for profile in cloned.get("profiles", []):
        api_key = str(profile.get("api_key", ""))
        profile["api_key"] = _encrypt_secret(api_key)
    return cloned


def _validate_base_url(base_url: str, field: str):
    if not base_url or not base_url.strip():
        raise ConfigValidationError("MISSING_BASE_URL", "API Base URL 不能为空", field)
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigValidationError("INVALID_BASE_URL", "API Base URL 格式无效，需以 http:// 或 https:// 开头", field)
    if len(base_url) > 200:
        raise ConfigValidationError("BASE_URL_TOO_LONG", "API Base URL 长度不能超过 200", field)


def _validate_parser_config(parser: Any, field_prefix: str = "parser") -> Dict[str, Any]:
    if parser is None:
        parser = {}
    if not isinstance(parser, dict):
        raise ConfigValidationError("INVALID_PARSER_CONFIG", "解析配置格式无效", field_prefix)

    backend = str(parser.get("parser_backend", "docling")).strip().lower() or "docling"
    if backend not in {"docling", "marker", "hybrid"}:
        raise ConfigValidationError(
            "INVALID_PARSER_BACKEND",
            "解析后端仅支持 docling / marker / hybrid",
            f"{field_prefix}.parser_backend",
        )

    def _as_float(name: str, min_v: float, max_v: float, default: float) -> float:
        raw = parser.get(name, default)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            raise ConfigValidationError(
                f"INVALID_{name.upper()}",
                f"{name} 必须是数字",
                f"{field_prefix}.{name}",
            )
        if val < min_v or val > max_v:
            raise ConfigValidationError(
                f"OUT_OF_RANGE_{name.upper()}",
                f"{name} 必须在 {min_v} 到 {max_v} 之间",
                f"{field_prefix}.{name}",
            )
        return val

    def _as_int(name: str, min_v: int, max_v: int, default: int) -> int:
        raw = parser.get(name, default)
        try:
            val = int(raw)
        except (TypeError, ValueError):
            raise ConfigValidationError(
                f"INVALID_{name.upper()}",
                f"{name} 必须是整数",
                f"{field_prefix}.{name}",
            )
        if val < min_v or val > max_v:
            raise ConfigValidationError(
                f"OUT_OF_RANGE_{name.upper()}",
                f"{name} 必须在 {min_v} 到 {max_v} 之间",
                f"{field_prefix}.{name}",
            )
        return val

    marker_prefer_api_raw = parser.get("marker_prefer_api", False)
    if isinstance(marker_prefer_api_raw, bool):
        marker_prefer_api = marker_prefer_api_raw
    else:
        marker_prefer_api = str(marker_prefer_api_raw).strip().lower() in {"1", "true", "yes", "on"}

    return {
        "parser_backend": backend,
        "hybrid_noise_threshold": _as_float("hybrid_noise_threshold", 0.0, 1.0, 0.20),
        "hybrid_docling_skip_score": _as_float("hybrid_docling_skip_score", 0.0, 100.0, 70.0),
        "hybrid_switch_min_delta": _as_float("hybrid_switch_min_delta", 0.0, 50.0, 2.0),
        "hybrid_marker_min_length": _as_int("hybrid_marker_min_length", 0, 1000000, 200),
        "marker_prefer_api": marker_prefer_api,
    }


def _validate_profile(profile: Dict[str, Any], field_prefix: str = "profile") -> Dict[str, Any]:
    profile_id = str(profile.get("id", "")).strip()
    if not profile_id:
        raise ConfigValidationError("MISSING_PROFILE_ID", "配置档案缺少 ID", f"{field_prefix}.id")
    if len(profile_id) > 80:
        raise ConfigValidationError("PROFILE_ID_TOO_LONG", "配置档案 ID 长度不能超过 80", f"{field_prefix}.id")

    name = str(profile.get("name", "")).strip()
    if not name:
        raise ConfigValidationError("MISSING_PROFILE_NAME", "配置档案名称不能为空", f"{field_prefix}.name")
    if len(name) > 60:
        raise ConfigValidationError("PROFILE_NAME_TOO_LONG", "配置档案名称长度不能超过 60", f"{field_prefix}.name")

    base_url = str(profile.get("base_url", "")).strip()
    _validate_base_url(base_url, f"{field_prefix}.base_url")

    model = str(profile.get("model", "")).strip()
    if not model:
        raise ConfigValidationError("MISSING_MODEL", "模型名称不能为空", f"{field_prefix}.model")
    if len(model) > 120:
        raise ConfigValidationError("MODEL_NAME_TOO_LONG", "模型名称长度不能超过 120", f"{field_prefix}.model")

    account_type = str(profile.get("account_type", "free")).strip().lower() or "free"
    if account_type not in {"free", "paid"}:
        raise ConfigValidationError("INVALID_ACCOUNT_TYPE", "账户类型仅支持 free 或 paid", f"{field_prefix}.account_type")

    provider = str(profile.get("provider", "custom")).strip().lower() or "custom"
    if provider not in DEFAULT_PROVIDER_PRESETS:
        raise ConfigValidationError("INVALID_PROVIDER", f"不支持的 provider: {provider}", f"{field_prefix}.provider")
    api_key = str(profile.get("api_key", ""))
    if len(api_key) > 1024:
        raise ConfigValidationError("API_KEY_TOO_LONG", "API Key 长度不能超过 1024", f"{field_prefix}.api_key")
    if _is_ollama_url(base_url) and api_key and api_key != MASKED_SECRET:
        # 允许填写但给出温和规范（自动忽略）
        logger.info("检测到 Ollama 配置，API Key 将按本地模式处理")
    manual_models = _normalize_models(profile.get("manual_models"))

    return {
        "id": profile_id,
        "name": name,
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "account_type": account_type,
        "manual_models": manual_models,
    }


def _migrate_legacy_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    profile = _default_profile()
    profile.update({
        "base_url": str(raw.get("base_url") or profile["base_url"]).strip(),
        "model": str(raw.get("model") or profile["model"]).strip(),
        "api_key": str(raw.get("api_key", "")),
        "account_type": str(raw.get("account_type", "free")).strip().lower() or "free",
    })
    profile = _validate_profile(profile, "profiles[0]")
    parser = _validate_parser_config(raw.get("parser", _default_parser_config()), "parser")
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "active_profile_id": profile["id"],
        "profiles": [profile],
        "parser": parser,
    }


def _normalize_config_store(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}

    if "profiles" not in raw:
        return _migrate_legacy_config(raw)

    profiles_raw = raw.get("profiles")
    if not isinstance(profiles_raw, list) or not profiles_raw:
        raise ConfigValidationError("EMPTY_PROFILES", "至少需要一个配置档案", "profiles")

    profiles = []
    seen_ids = set()
    for idx, item in enumerate(profiles_raw):
        if not isinstance(item, dict):
            raise ConfigValidationError("INVALID_PROFILE", "配置档案格式无效", f"profiles[{idx}]")
        cleaned = _validate_profile(item, f"profiles[{idx}]")
        if cleaned["id"] in seen_ids:
            raise ConfigValidationError("DUPLICATE_PROFILE_ID", f"配置档案 ID 重复: {cleaned['id']}", f"profiles[{idx}].id")
        seen_ids.add(cleaned["id"])
        profiles.append(cleaned)

    active_profile_id = str(raw.get("active_profile_id", "")).strip()
    if not active_profile_id:
        active_profile_id = profiles[0]["id"]

    if active_profile_id not in seen_ids:
        raise ConfigValidationError("ACTIVE_PROFILE_NOT_FOUND", "激活配置档案不存在", "active_profile_id")

    parser = _validate_parser_config(raw.get("parser", _default_parser_config()), "parser")

    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "active_profile_id": active_profile_id,
        "profiles": profiles,
        "parser": parser,
    }


def _load_config_store() -> Dict[str, Any]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            _decrypt_store_inplace(raw)
            return _normalize_config_store(raw)
        except ConfigValidationError as e:
            logger.warning(f"配置文件结构无效，将回退默认配置: {e.message}")
        except Exception as e:
            logger.warning(f"读取配置失败，将回退默认配置: {e}")

    return _migrate_legacy_config({})


def _save_config_store(config_store: Dict[str, Any]):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    encrypted_store = _encrypt_store_for_disk(config_store)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(encrypted_store, f, ensure_ascii=False, indent=2)


def _find_profile(config_store: Dict[str, Any], profile_id: str) -> Optional[Dict[str, Any]]:
    for profile in config_store.get("profiles", []):
        if profile.get("id") == profile_id:
            return profile
    return None


def _active_profile(config_store: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    profile_id = config_store.get("active_profile_id", "")
    profile = _find_profile(config_store, profile_id)
    return profile or (config_store.get("profiles") or [None])[0]


def _merge_masked_api_keys(incoming: Dict[str, Any], existing: Dict[str, Any]) -> Dict[str, Any]:
    existing_map = {item.get("id"): item for item in existing.get("profiles", [])}
    merged_profiles = []
    for profile in incoming.get("profiles", []):
        current = dict(profile)
        api_key = current.get("api_key", "")
        if api_key == MASKED_SECRET:
            previous = existing_map.get(current.get("id"), {})
            current["api_key"] = previous.get("api_key", "")
        merged_profiles.append(current)
    incoming["profiles"] = merged_profiles
    return incoming


def _profile_to_runtime(profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "base_url": profile.get("base_url", ""),
        "model": profile.get("model", ""),
        "api_key": profile.get("api_key", ""),
        "account_type": profile.get("account_type", "free"),
    }


def _config_to_view(config_store: Dict[str, Any]) -> ConfigStoreView:
    profiles_view = []
    for profile in config_store.get("profiles", []):
        api_key = profile.get("api_key", "")
        profiles_view.append(
            ProfileView(
                id=profile.get("id", ""),
                name=profile.get("name", ""),
                provider=profile.get("provider", "custom"),
                base_url=profile.get("base_url", ""),
                model=profile.get("model", ""),
                api_key=MASKED_SECRET if api_key else "",
                has_api_key=bool(api_key),
                account_type=profile.get("account_type", "free"),
                manual_models=profile.get("manual_models", []),
            )
        )
    return ConfigStoreView(
        schema_version=CONFIG_SCHEMA_VERSION,
        active_profile_id=config_store.get("active_profile_id", ""),
        profiles=profiles_view,
        parser=_validate_parser_config(config_store.get("parser", _default_parser_config()), "parser"),
    )


def _config_export_payload(config_store: Dict[str, Any]) -> Dict[str, Any]:
    profiles = []
    for profile in config_store.get("profiles", []):
        profiles.append({
            "id": profile.get("id", ""),
            "name": profile.get("name", ""),
            "provider": profile.get("provider", "custom"),
            "base_url": profile.get("base_url", ""),
            "model": profile.get("model", ""),
            "account_type": profile.get("account_type", "free"),
            "manual_models": profile.get("manual_models", []),
            # 导出不含明文密钥；仅标记是否存在，导入后可复用同 id 的已有密钥
            "api_key": "",
            "has_api_key": bool(profile.get("api_key", "")),
        })
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "active_profile_id": config_store.get("active_profile_id", ""),
        "profiles": profiles,
        "parser": _validate_parser_config(config_store.get("parser", _default_parser_config()), "parser"),
    }


def _apply_runtime_config(config_store: Dict[str, Any]):
    parser_config = _validate_parser_config(config_store.get("parser", _default_parser_config()), "parser")
    update_parser_runtime_config(parser_config)

    profile = _active_profile(config_store)
    if not profile:
        logger.info("未找到可用配置档案，请在前端设置（解析配置已生效）")
        return

    runtime_config = _profile_to_runtime(profile)
    if not runtime_config.get("api_key") and not _is_ollama_url(runtime_config.get("base_url", "")):
        logger.info("当前激活配置缺少 API Key，请在前端设置")
        return

    update_client_config(runtime_config)
    set_model(runtime_config.get("model", "deepseek-chat"))
    set_account_type(runtime_config.get("account_type", "free"))
    logger.info(
        f"配置已应用: profile={profile.get('name')} ({profile.get('provider')}), "
        f"parser_backend={parser_config.get('parser_backend')}"
    )


def _map_error_code(error_text: str) -> str:
    lowered = (error_text or "").lower()
    if "401" in lowered or "authentication" in lowered:
        return "AUTH_FAILED"
    if "403" in lowered:
        return "PERMISSION_DENIED"
    if "404" in lowered:
        return "RESOURCE_NOT_FOUND"
    if "429" in lowered or "rate limit" in lowered:
        return "RATE_LIMITED"
    if "timeout" in lowered:
        return "NETWORK_TIMEOUT"
    if "connection refused" in lowered or "econnrefused" in lowered:
        return "CONNECTION_REFUSED"
    return "UNKNOWN_ERROR"


def _extract_profile_payload(payload: Dict[str, Any], existing_store: Dict[str, Any]) -> Dict[str, Any]:
    if "profile" in payload and isinstance(payload["profile"], dict):
        profile = _validate_profile(payload["profile"], "profile")
    else:
        profile = _validate_profile(payload, "profile")

    if profile.get("api_key") == MASKED_SECRET:
        previous = _find_profile(existing_store, profile.get("id", ""))
        profile["api_key"] = previous.get("api_key", "") if previous else ""

    return profile


# ==================== 启动时配置 ====================
@app.on_event("startup")
async def startup_event():
    """启动时加载配置"""
    try:
        config_store = _load_config_store()
        _apply_runtime_config(config_store)
    except Exception as e:
        logger.warning(f"启动时加载配置失败：{e}")

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

# ==================== 目录定义 ====================
# 文件存储目录 - 使用绝对路径
# BASE_DIR 已在配置管理部分定义
DATA_DIR = os.path.join(BASE_DIR, "data")
PDF_DIR = os.path.join(DATA_DIR, "pdfs")
MD_DIR = os.path.join(DATA_DIR, "mds")
IMAGES_DIR = os.path.join(DATA_DIR, "images")  # 新增图片目录
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

# 确保目录存在
os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(MD_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)

# 挂载静态图片目录 (Step 2)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

# ==================== 数据模型 ====================

from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Task:
    def __init__(self, task_id: str, file_id: Optional[str] = None):
        self.task_id = task_id
        self.file_id = file_id
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.message = "等待处理..."
        self.result = None
        self.error = None

class FileRecord(BaseModel):
    file_id: str
    task_id: Optional[str] = None
    filename: str
    file_hash: str
    pdf_path: str
    md_path: str
    created_at: str
    status: str  # "completed", "processing", "failed"

# ==================== 任务存储（内存） ====================
# 注意：服务重启后任务状态丢失，这对单用户桌面应用是可接受的
tasks: Dict[str, "Task"] = {}

def create_task(task_id: str, file_id: Optional[str] = None) -> "Task":
    """创建并注册新任务"""
    task = Task(task_id, file_id=file_id)
    tasks[task_id] = task
    return task

def get_task(task_id: str) -> "Task":
    """根据 task_id 获取任务，不存在则返回 None"""
    return tasks.get(task_id)

# ==================== 文件 Hash ====================

def get_file_hash(file_path: str) -> str:
    """计算文件 MD5，用于去重检测"""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# ==================== 历史记录管理 ====================
# 使用 JSON 文件持久化，RLock 防止并发读写冲突
_history_lock = threading.RLock()

def load_history() -> List[Dict]:
    """同步读取历史记录（加锁避免读写竞争）"""
    with _history_lock:
        if not os.path.exists(HISTORY_FILE):
            return []
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取历史记录失败: {e}")
            return []

def _save_history_sync(history: List[Dict]):
    """同步写入历史记录（内部使用）"""
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def add_file_record(
    file_id: str,
    filename: str,
    file_hash: str,
    pdf_path: str,
    md_path: str,
    status: str,
    task_id: str = None,
):
    """添加或更新文件记录（同步，调用方已在后台任务中）"""
    with _history_lock:
        history = load_history()

        # 如果已存在同 file_id 的记录，先移除旧记录
        history = [item for item in history if item.get("file_id") != file_id]

        record = {
            "file_id": file_id,
            "task_id": task_id,
            "filename": filename,
            "file_hash": file_hash,
            "pdf_path": pdf_path,
            "md_path": md_path,
            "created_at": datetime.now().isoformat(),
            "status": status,
        }
        history.append(record)
        _save_history_sync(history)
    logger.info(f"文件记录已保存: {file_id} ({status})")

def update_file_status(file_id: str, status: str, md_path: str = None):
    """更新文件处理状态"""
    with _history_lock:
        history = load_history()
        for item in history:
            if item.get("file_id") == file_id:
                item["status"] = status
                if md_path:
                    item["md_path"] = md_path
                break
        _save_history_sync(history)

def delete_file_record(file_id: str) -> bool:
    """删除文件记录，返回是否成功"""
    with _history_lock:
        history = load_history()
        new_history = [item for item in history if item.get("file_id") != file_id]
        if len(new_history) == len(history):
            return False  # 未找到
        _save_history_sync(new_history)
        return True

def check_file_exists(file_hash: str) -> Dict:
    """根据 MD5 检查文件是否已存在，返回记录或 None"""
    with _history_lock:
        history = load_history()
        for item in history:
            if item.get("file_hash") == file_hash:
                return item
    return None

# ==================== 后台任务 ====================

async def process_document_task(task_id: str, file_location: str, file_id: str, original_filename: str):
    """
    异步处理文档任务 - Skeleton-Refinement Strategy
    """
    logger.info(f"开始处理任务：{task_id}")
    task = get_task(task_id)

    if not task:
        logger.error(f"任务不存在：{task_id}")
        return

    try:
        task.file_id = file_id
        # 阶段 1: PDF 解析 (0-10%)
        task.status = TaskStatus.PROCESSING
        task.progress = 5
        task.message = "正在解析 PDF 文档..."
        logger.info(f"任务 {task_id}: 开始解析 PDF")

        # Run CPU-bound task in a separate thread to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        import functools
        md_content, image_map = await loop.run_in_executor(
            None, 
            functools.partial(process_pdf_safely, file_location, output_dir=MD_DIR, file_id=file_id)
        )

        if not md_content:
            logger.error(f"PDF 解析失败: {file_location}")
            raise Exception("PDF 解析失败")

        task.progress = 10
        task.message = "文档解析完成，正在构建知识骨架..."
        logger.info(f"任务 {task_id}: PDF 解析完成")
        
        # 阶段 2: 构建骨架 (10-20%)
        from structure_utils import build_hierarchy_tree, tree_to_markdown
        
        root_node = build_hierarchy_tree(md_content)
        
        # 收集需要 Refinement 的节点
        nodes_to_refine = []
        
        def collect_nodes(node):
            # 策略：只处理有内容的叶子节点或包含大量文本的中间节点
            # 以及 Root 下的"孤儿内容"
            content_len = len(node.full_content)
            
            # Refinement 1: Empty Node Handling (Skip small container nodes)
            if content_len > 50:
                nodes_to_refine.append(node)
            
            for child in node.children:
                collect_nodes(child)
                
        collect_nodes(root_node)
        
        task.progress = 20
        task.message = f"知识骨架构建完成，共发现 {len(nodes_to_refine)} 个关键章节..."
        logger.info(f"Tree built. Nodes to refine: {len(nodes_to_refine)}")

        # 阶段 3: 并行 Refinement (20-95%)
        from cognitive_engine import refine_node_content
        
        # Refinement 2: Concurrency Control
        semaphore = asyncio.Semaphore(5)
        total_nodes = len(nodes_to_refine)
        completed_count = 0
        
        async def process_node(node):
            nonlocal completed_count
            async with semaphore:
                try:
                    # Refinement 3: Context Breadcrumbs
                    context_path = node.get_breadcrumbs()
                    
                    details = await refine_node_content(
                        node_title=node.topic,
                        content_chunk=node.full_content,
                        context_path=context_path
                    )
                    
                    if details:
                        node.ai_details = details
                    
                    # 更新进度
                    completed_count += 1
                    current_progress = 20 + int((completed_count / total_nodes) * 75)
                    task.progress = min(95, current_progress)
                    if completed_count % 5 == 0:
                        task.message = f"AI 正在深入分析章节 ({completed_count}/{total_nodes})..."
                        
                except Exception as e:
                    logger.error(f"Node processing failed: {e}")
                    
        if nodes_to_refine:
            tasks_list = [process_node(n) for n in nodes_to_refine]
            await asyncio.gather(*tasks_list)
        else:
            logger.warning("No nodes required refinement.")

        # 阶段 4: 组装与导出 (95-100%)
        task.progress = 98
        task.message = "正在组装最终图谱..."
        
        final_md = tree_to_markdown(root_node)
        
        # 添加根节点标题 (如果 Root 没有显示)
        # tree_to_markdown 默认不打印 Root，我们手动加一个 H1
        doc_title = original_filename.replace('.pdf', '')
        if not final_md.startswith('# '):
            final_md = f"# {doc_title}\n\n{final_md}"

        # 保存 MD 文件
        md_path = os.path.join(MD_DIR, f"{file_id}.md")
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(final_md)

        # 更新文件记录状态
        update_file_status(file_id, 'completed', md_path)

        task.status = TaskStatus.COMPLETED
        task.progress = 100
        task.message = "处理完成！"
        task.result = final_md
        logger.info(f"任务 {task_id}: 处理完成")

    except Exception as e:
        logger.error(f"任务 {task_id} 处理失败：{e}", exc_info=True)
        task.status = TaskStatus.FAILED
        task.error = str(e)
        task.message = f"处理失败：{str(e)}"
        update_file_status(file_id, 'failed')

# ==================== API 路由 ====================

class TaskResponse(BaseModel):
    task_id: str
    file_id: Optional[str] = None
    status: str
    progress: int
    message: str
    result: Optional[str] = None
    error: Optional[str] = None

class UploadResponse(BaseModel):
    task_id: str
    file_id: str
    status: str
    message: str
    is_duplicate: bool = False
    existing_md: Optional[str] = None

class HistoryItem(BaseModel):
    file_id: str
    filename: str
    file_hash: str
    md_path: str
    created_at: str
    status: str

@app.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """
    上传文档，创建异步任务
    """
    # 生成唯一 ID
    file_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    logger.info(f"收到上传请求：{file_id}, 文件名：{file.filename}")

    # 保存文件
    temp_file = os.path.join(DATA_DIR, "temp", f"{file_id}_{file.filename}")
    os.makedirs(os.path.dirname(temp_file), exist_ok=True)

    try:
        with open(temp_file, "wb+") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"文件已保存：{temp_file}")
    except Exception as e:
        logger.error(f"文件保存失败：{e}")
        raise HTTPException(status_code=500, detail=f"文件保存失败：{str(e)}")

    # 计算文件 Hash
    file_hash = get_file_hash(temp_file)
    logger.info(f"文件 Hash: {file_hash}")

    # 检查是否重复
    existing = check_file_exists(file_hash)
    if existing:
        existing_status = existing.get('status')

        if existing_status == 'completed':
            # 情况 1: 已完成，直接复用 MD 结果
            # 删除临时文件
            os.remove(temp_file)

            # 获取已存在的 MD
            existing_md = ""
            if os.path.exists(existing['md_path']):
                with open(existing['md_path'], 'r', encoding='utf-8') as f:
                    existing_md = f.read()

            logger.info(f"检测到重复文件（已完成）：{file.filename}")
            return UploadResponse(
                task_id=task_id,
                file_id=existing['file_id'],
                status="completed",
                message="文件已存在，直接加载",
                is_duplicate=True,
                existing_md=existing_md
            )

        elif existing_status == 'failed':
            # 情况 2: 之前处理失败，复用 PDF 文件，重新创建任务
            old_file_id = existing['file_id']
            pdf_path = existing.get('pdf_path')

            if not pdf_path or not os.path.exists(pdf_path):
                # PDF 文件不存在，删除临时文件并当作新文件处理
                logger.warning(f"失败任务的 PDF 文件不存在：{pdf_path}")
                # 继续执行后续逻辑，当作新文件处理
            else:
                # 复用现有 PDF 文件，删除临时文件
                os.remove(temp_file)

                # 更新原记录状态为 processing
                md_path = os.path.join(MD_DIR, f"{old_file_id}.md")
                add_file_record(old_file_id, existing['filename'], file_hash, pdf_path, md_path, "processing", task_id=task_id)

                # 创建新任务，使用原有 PDF 路径
                task = create_task(task_id, file_id=old_file_id)
                asyncio.create_task(process_document_task(task_id, pdf_path, old_file_id, existing['filename']))

                logger.info(f"检测到失败任务，重新处理：{file.filename}, file_id={old_file_id}")
                return UploadResponse(
                    task_id=task_id,
                    file_id=old_file_id,
                    status="processing",
                    message="检测到之前处理失败，正在重新处理..."
                )
        elif existing_status == 'processing':
            # 情况 3: 已在处理中的重复上传，复用正在运行任务；若任务丢失则自动重启
            old_file_id = existing['file_id']
            old_task_id = existing.get('task_id')
            pdf_path = existing.get('pdf_path')

            # 删除本次临时上传文件，避免重复占用磁盘
            os.remove(temp_file)

            existing_task = get_task(old_task_id) if old_task_id else None
            if existing_task and existing_task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING}:
                logger.info(f"检测到处理中重复文件，复用任务：task_id={old_task_id}, file_id={old_file_id}")
                return UploadResponse(
                    task_id=old_task_id,
                    file_id=old_file_id,
                    status="processing",
                    message="文件正在处理中，已连接到现有任务",
                    is_duplicate=True
                )

            if pdf_path and os.path.exists(pdf_path):
                restarted_task_id = str(uuid.uuid4())
                md_path = os.path.join(MD_DIR, f"{old_file_id}.md")
                add_file_record(
                    old_file_id,
                    existing['filename'],
                    file_hash,
                    pdf_path,
                    md_path,
                    "processing",
                    task_id=restarted_task_id
                )
                create_task(restarted_task_id, file_id=old_file_id)
                asyncio.create_task(process_document_task(restarted_task_id, pdf_path, old_file_id, existing['filename']))
                logger.info(f"历史处理中任务已失效，自动重启：task_id={restarted_task_id}, file_id={old_file_id}")
                return UploadResponse(
                    task_id=restarted_task_id,
                    file_id=old_file_id,
                    status="processing",
                    message="检测到历史任务已失效，已自动重新处理",
                    is_duplicate=True
                )

            logger.warning(f"处理中记录缺失源 PDF，按新文件处理：file_id={old_file_id}")

    # 新文件：移动到正式目录
    pdf_path = os.path.join(PDF_DIR, f"{file_id}_{file.filename}")
    shutil.move(temp_file, pdf_path)

    # 创建文件记录
    md_path = os.path.join(MD_DIR, f"{file_id}.md")
    add_file_record(file_id, file.filename, file_hash, pdf_path, md_path, "processing", task_id=task_id)

    # 创建任务
    task = create_task(task_id, file_id=file_id)

    # 启动后台任务
    asyncio.create_task(process_document_task(task_id, pdf_path, file_id, file.filename))
    logger.info(f"后台任务已创建：{task_id}")

    return UploadResponse(
        task_id=task_id,
        file_id=file_id,
        status="processing",
        message="任务已创建，正在处理..."
    )

@app.get("/task/{task_id}", response_model=TaskResponse)
async def get_task_status(task_id: str):
    """
    获取任务状态，支持重启后查询
    """
    task = get_task(task_id)

    if not task:
        logger.warning(f"任务不存在：{task_id}")
        raise HTTPException(status_code=404, detail="任务不存在")

    return TaskResponse(
        task_id=task.task_id,
        file_id=task.file_id,
        status=task.status,
        progress=task.progress,
        message=task.message,
        result=task.result,
        error=task.error
    )

@app.get("/history", response_model=List[HistoryItem])
async def get_history():
    """
    获取文件历史列表
    """
    history = load_history()
    # 只需要关键字段
    return [
        HistoryItem(
            file_id=item['file_id'],
            filename=item['filename'],
            file_hash=item['file_hash'],
            md_path=item['md_path'],
            created_at=item['created_at'],
            status=item['status']
        )
        for item in history
    ]

@app.get("/file/{file_id}")
async def get_file_content(file_id: str):
    """
    获取文件的 MD 内容
    """
    history = load_history()
    for item in history:
        if item['file_id'] == file_id:
            if item['status'] != 'completed':
                raise HTTPException(status_code=400, detail="文件尚未处理完成")

            if not os.path.exists(item['md_path']):
                raise HTTPException(status_code=404, detail="文件内容不存在")

            with open(item['md_path'], 'r', encoding='utf-8') as f:
                content = f.read()

            return {"content": content, "filename": item['filename']}

    raise HTTPException(status_code=404, detail="文件记录不存在")

@app.delete("/file/{file_id}")
async def delete_file(file_id: str):
    """
    删除文件记录
    """
    history = load_history()
    record = next((item for item in history if item.get("file_id") == file_id), None)
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 先清理磁盘文件，再删除历史记录
    for path in [record.get("pdf_path"), record.get("md_path")]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                logger.warning(f"删除文件失败 ({path}): {e}")

    image_dir = os.path.join(IMAGES_DIR, file_id)
    if os.path.isdir(image_dir):
        try:
            shutil.rmtree(image_dir)
        except Exception as e:
            logger.warning(f"删除图片目录失败 ({image_dir}): {e}")

    tasks.pop(record.get("task_id"), None)
    if delete_file_record(file_id):
        return {"message": "文件已删除"}
    raise HTTPException(status_code=500, detail="删除历史记录失败")

@app.get("/export/xmind/{file_id}")
async def export_xmind(file_id: str):
    """
    导出 XMind 格式
    """
    from fastapi.responses import Response

    history = load_history()
    for item in history:
        if item['file_id'] == file_id:
            if item['status'] != 'completed':
                raise HTTPException(status_code=400, detail="文件尚未处理完成")

            if not os.path.exists(item['md_path']):
                raise HTTPException(status_code=404, detail="文件内容不存在")

            with open(item['md_path'], 'r', encoding='utf-8') as f:
                content = f.read()

            # 生成 XMind
            # step 4: 传入图片目录
            images_dir = os.path.join(IMAGES_DIR, file_id)
            xmind_data = generate_xmind_content(content, item['filename'], images_dir=images_dir)

            filename = item['filename'].replace('.pdf', '') + '.xmind'

            return Response(
                content=xmind_data,
                media_type="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

    raise HTTPException(status_code=404, detail="文件记录不存在")

@app.post("/export/xmind")
async def export_xmind_from_content(request: Request):
    """
    直接从 Markdown 数据导出 XMind
    """
    request_data = await request.json()
    content = request_data.get('content', '')
    filename = request_data.get('filename', 'mindmap')

    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")

    xmind_data = generate_xmind_content(content, filename)

    return Response(
        content=xmind_data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}.xmind"}
    )

@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}

from hardware_utils import get_hardware_info

@app.get("/system/hardware")
async def check_hardware_status():
    """前端轮询此接口以决定是否弹窗警告"""
    info = get_hardware_info()
    logger.info(f"前端查询硬件状态: {info}")
    return info

# ==================== 配置 API ====================
@app.get("/config", response_model=ConfigStoreView)
async def get_config():
    """获取配置中心数据（多 profile）"""
    config_store = _load_config_store()
    return _config_to_view(config_store)


@app.get("/config/export")
async def export_config():
    """导出配置（不含明文密钥）"""
    config_store = _load_config_store()
    return _config_export_payload(config_store)


@app.post("/config/import")
async def import_config(payload: ConfigImportPayload):
    """导入配置（不含密钥时可按 profile id 复用本地已保存密钥）"""
    try:
        raw_payload = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        # 支持导出文件中的附加字段（如 exported_at）
        normalized = _normalize_config_store({
            "active_profile_id": raw_payload.get("active_profile_id", ""),
            "profiles": raw_payload.get("profiles", []),
            "parser": raw_payload.get("parser", _default_parser_config()),
        })
        existing = _load_config_store()

        # 导入数据中 api_key 为空但标注 has_api_key=true 时，自动尝试保留旧密钥
        existing_map = {item.get("id"): item for item in existing.get("profiles", [])}
        for profile in normalized.get("profiles", []):
            if not profile.get("api_key") and any(
                item.get("id") == profile.get("id") and item.get("has_api_key")
                for item in raw_payload.get("profiles", [])
                if isinstance(item, dict)
            ):
                previous = existing_map.get(profile.get("id"), {})
                profile["api_key"] = previous.get("api_key", "")

        normalized = _merge_masked_api_keys(normalized, existing)
        _save_config_store(normalized)
        _apply_runtime_config(normalized)
        return {
            "success": True,
            "message": "配置导入成功",
            "active_profile_id": normalized.get("active_profile_id"),
            "profiles_count": len(normalized.get("profiles", [])),
        }
    except ConfigValidationError as e:
        raise HTTPException(status_code=422, detail=e.to_detail())
    except Exception as e:
        logger.error(f"导入配置失败：{e}")
        raise HTTPException(
            status_code=500,
            detail={"code": "CONFIG_IMPORT_FAILED", "message": f"导入配置失败: {str(e)}"},
        )


@app.post("/config")
async def set_config(request: Request):
    """保存配置中心数据（支持 legacy payload 自动迁移）"""
    try:
        payload = await request.json()
        normalized = _normalize_config_store(payload)
        existing = _load_config_store()
        normalized = _merge_masked_api_keys(normalized, existing)
        _save_config_store(normalized)

        try:
            _apply_runtime_config(normalized)
        except Exception as runtime_err:
            # 配置保存成功但运行时应用失败时，返回可诊断信息
            logger.warning(f"配置已保存，但运行时应用失败: {runtime_err}")
            return {
                "success": False,
                "code": _map_error_code(str(runtime_err)),
                "message": f"配置已保存，但激活配置应用失败: {runtime_err}",
                "active_profile_id": normalized.get("active_profile_id"),
            }

        return {
            "success": True,
            "message": "配置已保存",
            "active_profile_id": normalized.get("active_profile_id"),
        }
    except ConfigValidationError as e:
        raise HTTPException(status_code=422, detail=e.to_detail())
    except Exception as e:
        logger.error(f"保存配置失败：{e}")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "CONFIG_SAVE_FAILED",
                "message": f"保存配置失败: {str(e)}",
            },
        )


@app.post("/config/test")
async def test_config(request: Request):
    """测试单个 profile 配置"""
    try:
        request_data = await request.json()
        existing = _load_config_store()
        profile = _extract_profile_payload(request_data, existing)
        runtime_profile = _profile_to_runtime(profile)

        result = await test_connection(runtime_profile)
        if not result.get("success"):
            result["code"] = _map_error_code(result.get("message", ""))
        else:
            result["code"] = "OK"
        return result
    except ConfigValidationError as e:
        return {"success": False, "code": e.code, "message": e.message, "field": e.field}
    except Exception as e:
        logger.error(f"测试配置失败：{e}")
        return {"success": False, "code": "INTERNAL_ERROR", "message": f"内部错误：{str(e)}"}


@app.post("/config/models")
async def load_models(request: ModelListRequest):
    """动态拉取模型列表；失败时返回手动白名单作为降级来源"""
    try:
        existing = _load_config_store()
        profile_payload = request.profile.model_dump() if hasattr(request.profile, "model_dump") else request.profile.dict()
        profile = _extract_profile_payload({"profile": profile_payload}, existing)
        runtime_profile = _profile_to_runtime(profile)

        from cognitive_engine import fetch_models_detailed

        fetch_result = await fetch_models_detailed(
            base_url=runtime_profile.get("base_url", ""),
            api_key=runtime_profile.get("api_key", ""),
        )

        if fetch_result.get("success") and fetch_result.get("models"):
            return {
                "success": True,
                "source": "remote",
                "models": fetch_result.get("models", []),
                "message": f"已拉取 {len(fetch_result.get('models', []))} 个模型",
                "code": "OK",
            }

        manual_models = profile.get("manual_models", [])
        if manual_models:
            return {
                "success": True,
                "source": "manual",
                "models": manual_models,
                "message": "远程模型列表不可用，已回退到手动白名单",
                "code": _map_error_code(fetch_result.get("error", "")),
            }

        return {
            "success": False,
            "source": "none",
            "models": [],
            "message": fetch_result.get("error", "无法获取模型列表"),
            "code": _map_error_code(fetch_result.get("error", "")),
        }
    except ConfigValidationError as e:
        return {"success": False, "source": "none", "models": [], "code": e.code, "message": e.message, "field": e.field}
    except Exception as e:
        logger.error(f"拉取模型列表失败：{e}")
        return {"success": False, "source": "none", "models": [], "code": "INTERNAL_ERROR", "message": f"内部错误：{str(e)}"}
