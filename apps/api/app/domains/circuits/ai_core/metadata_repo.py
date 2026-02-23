# app/domains/circuits/ai_core/metadata_repo.py
""" Metadata Repository - Load và tra cứu functional metadata.
Cung cấp:
  - load_all(): load toàn bộ metadata files
  - find_by_family(): tìm theo family
  - find_by_pattern(): tìm theo block pattern signature
  - find_by_capabilities(): tìm theo required capabilities
  - get_by_template_id(): lấy theo template_id
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

""" lý do sử dụng thư viện
json: load metadata files (thư viện toàn file.json =))
logging: ghi log quá trình load metadata
pathlib: xử lý đường dẫn file metadata
typing: type hints cho readability và maintainability
"""

logger = logging.getLogger(__name__)

# Path mặc định tới thư mục metadata
# __file__ → ai_core/ → circuits/ → domains/ → app/ → (api/) → resources/
_API_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent  # apps/api/
_DEFAULT_METADATA_DIR = _API_ROOT / "resources" / "templates_metadata"
_DEFAULT_BLOCK_LIBRARY_DIR = _API_ROOT / "resources" / "block_library"


class MetadataRepository:
    """ Repository quản lý metadata chức năng cho mạch điện tử.
    - Áp dụng pattern repository, chỉ đọc (immutable) sau khi load.
    - Đảm bảo thread-safe: dữ liệu không thay đổi sau khi nạp vào bộ nhớ.
    - Hỗ trợ truy vấn metadata, block library, grammar rules.
    """
    def __init__(self, metadata_dir: Optional[Path] = None, block_library_dir: Optional[Path] = None,):
        self._metadata_dir = metadata_dir or _DEFAULT_METADATA_DIR
        self._block_library_dir = block_library_dir or _DEFAULT_BLOCK_LIBRARY_DIR
        self._metadata: Dict[str, Dict] = {}        # template_id → metadata dict
        self._block_library: Dict[str, Dict] = {}   # block_type → block define
        self._grammar_rules: Dict[str, Any] = {}    # topology rules
        self._loaded = False                        # cờ flag

    
    def load(self) -> None:
        """ Load toàn bộ dữ liệu repository vào memory:
         * metadata templates
         * block library
         * grammar rules
        """
        if self._is_already_loaded():
            logger.info("MetadataRepository already loaded, skipping.")
            return
        
        self._load_metadata_files()
        self._load_block_library()
        self._load_grammar_rules()
        
        self._mark_loaded()
        self._log_summary()

    def _is_already_loaded(self) -> bool:
        """ Ktra repository đã load chưa, tránh load nhiều lần. """
        return self._loaded
    
    def _load_metadata_files(self) -> None:
        """ load file*.meta.json trong metadata directory
         * mỗi file chứa metadata cho 1 template
         * lưu vào self._metadata theo key = template_id
        """
        meta_dir = Path(self._metadata_dir)
        
        if not meta_dir.exists():
            return
        
        for file in meta_dir.glob("*.meta.json"):
            try:
                with open(file, "r", encoding="utf-8") as fil_path:
                    data = json.load(fil_path)

                    # nếu không có templateID -> dùng tên file làm template_id
                    template_id = data.get("template_id", file.stem)
                    self._metadata[template_id] = data
            
            except (json.JSONDecodeError, KeyError) as error:
                logger.warning(f"Failed to load metadata {file.name}: {error}")
    
    def _load_block_library(self) -> None:
        """ load block library từ block_library.json
         * lưu vào self._block_library theo key = block_type theo cấu trúc
         { "blocks": { block_type: { ...block definition... } } }
        """
        bl_path = Path(self._block_library_dir) / "block_library.json"
        if not bl_path.exists():
            return

        with open(bl_path, "r", encoding="utf-8") as fil_path:
            data = json.load(fil_path)
        self._block_library = data.get("blocks", {})
        
    def _load_grammar_rules(self) -> None:
        """ Load grammar rule json
         * lưu vào self._grammar_rules theo cấu trúc
         { "topology_rules": { rule_name: { ...rule definition... } } }
        """
        gmar_path = Path(self._block_library_dir) / "grammar_rules.json"
        if not gmar_path.exists():
            return
        
        with open(gmar_path, "r", encoding="utf-8") as fil_path:
            data = json.load(fil_path)
        self._grammar_rules = data.get("topology_rules", {})
    
    def _mark_loaded(self) -> None:
        """ Đánh dấu đã load xong, tránh load lại nhiều lần. """
        self._loaded = True
        
    def _log_summary(self) -> None:
        """ tổng hợp số lượng dữ liệu đã load và ghi log. """
        logger.info(
            f"MetadataRepository loaded: {len(self._metadata)} metadata, "
                                       f"{len(self._block_library)} blocks, "
                                       f"{len(self._grammar_rules)} grammar rules"
        )
    
    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    
    # ── Phương thức truy vấn ──
    def load_all(self) -> List[Dict[str, Any]]:
        """ Trả về toàn bộ metadata. """
        self._ensure_loaded()
        return list(self._metadata.values())

    def get_by_template_id(self, template_id: str) -> Optional[Dict[str, Any]]:
        """ Lấy metadata theo template_id. """
        self._ensure_loaded()
        return self._metadata.get(template_id)

    def find_by_family(self, family: str) -> List[Dict[str, Any]]:
        """ Tìm metadata theo family (common_emitter, inverting, class_ab, ...). """
        self._ensure_loaded()
        results = []
        # duyệt các giá trị trong metadata (kiểm tra domain nếu có family khớp thi match và meta)
        for meta in self._metadata.values():
            if meta.get("domain", {}).get("family") == family:
                results.append(meta)
        
        # sắp xếp theo rank (h-l)
        results.sort(key=lambda m: m.get("planner_hints", {}).get("fallback_rank", 99))
        return results

    def find_by_category(self, category: str) -> List[Dict[str, Any]]:
        """ Tìm metadata theo category (bjt, mosfet, opamp, power_amplifier, special). """
        self._ensure_loaded()
        return [
            m for m in self._metadata.values()
            if m.get("domain", {}).get("category") == category
        ]

    def find_by_pattern(self, required_block_types: List[str], required_capabilities: Optional[List[str]] = None,) -> List[Dict[str, Any]]:
        """ Tìm metadata theo pattern signature (block types) + capabilities.
        Trả về danh sách sorted theo match score giảm dần.
        """
        self._ensure_loaded()
        results = []

        # tính toán score cho mỗi metadata dựa trên block type overlap và capability coverage
        for meta in self._metadata.values():
            fs = meta.get("functional_structure", {})
            sig = fs.get("pattern_signature", {})
            ordered = sig.get("ordered_block_types", [])
            hints = meta.get("planner_hints", {})

            # điểm = 0 nếu không match và >0 nếu có overlap block types (càng nhiều càng tốt)
            block_score = self._list_overlap_score(required_block_types, ordered)
            if block_score == 0:
                continue

            # điểm = 1 nếu có đầy đủ capabilities, <1 nếu thiếu một số capability (tỉ lệ coverage)
            cap_score = 1.0
            if required_capabilities:
                meta_caps = set(hints.get("required_capabilities", []))
                req_caps = set(required_capabilities)
                if req_caps:
                    cap_score = len(req_caps & meta_caps) / len(req_caps)

            # ưu tiên metadata có priority_score cao hơn (mặc định 0.5 nếu không có)
            priority = hints.get("priority_score", 0.5)
            total_score = block_score * 0.4 + cap_score * 0.4 + priority * 0.2

            results.append((total_score, meta))

        # sắp xếp theo tổng điểm giảm dần
        results.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in results]

    def find_by_capabilities(self, capabilities: List[str]) -> List[Dict[str, Any]]:
        """ Tìm metadata có chứa tất cả capabilities yêu cầu. """
        self._ensure_loaded()
        cap_set = set(capabilities)
        results = []
        
        # kiểm tra kết quả có chứa đầy đủ khả năng yêu cầu thì chọn, nếu thiếu thì bỏ qua
        for meta in self._metadata.values():
            hints = meta.get("planner_hints", {})
            meta_caps = set(hints.get("required_capabilities", []))
            if cap_set.issubset(meta_caps):
                results.append(meta)
        
        return results

    def find_nearest(self, family: str, required_capabilities: Optional[List[str]] = None,) -> Optional[Dict[str, Any]]:
        """ Tìm template gần nhất trong family, có capability match cao nhất. """
        candidates = self.find_by_family(family)
        if not candidates:
            return None
        if not required_capabilities:
            return candidates[0]

        best = None         # lưu khả năng tốt nhất
        best_score = -1     # lưu điểm tốt nhất (>= 0)
        
        for meta in candidates:
            hints = meta.get("planner_hints", {})
            meta_caps = set(hints.get("required_capabilities", []))
            score = len(set(required_capabilities) & meta_caps)
            priority = hints.get("priority_score", 0.5)
            total = score + priority
            
            if total > best_score:
                best_score = total
                best = meta

        return best

    # ── Truy cập thư viện block lấy theo type ──  
    def get_block_definition(self, block_type: str) -> Optional[Dict[str, Any]]:
        """ Trả về definition của block từ block library. """
        self._ensure_loaded()
        return self._block_library.get(block_type)

    def get_all_block_types(self) -> List[str]:
        """ Trả về danh sách tất cả block types. """
        self._ensure_loaded()
        return list(self._block_library.keys())

    
    # ── Truy cập các quy tắc kết nối để sinh mạch ──
    def get_grammar_rule(self, rule_name: str) -> Optional[Dict[str, Any]]:
        """ Trả về grammar rule theo tên. """
        self._ensure_loaded()
        return self._grammar_rules.get(rule_name)

    def get_grammar_rules_for_family(self, family: str) -> List[Dict[str, Any]]:
        """ Tìm grammar rules match với family. """
        self._ensure_loaded()
        results = []
        
        for name, rule in self._grammar_rules.items():
            match_families = rule.get("match_families", [])
            if family in match_families:
                results.append({"rule_name": name, **rule})
        
        return results

    def get_extension_rules(self) -> List[Dict[str, Any]]:
        """ Trả về danh sách extension rules. """
        self._ensure_loaded()
        gr_path = Path(self._block_library_dir) / "grammar_rules.json"
        
        if gr_path.exists():
            with open(gr_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data.get("extension_rules", {}).get("allowed_extensions", [])
        return []

    
    # ── Đóng gói hệ thống ──
    @staticmethod
    def _list_overlap_score(list_a: List[str], list_b: List[str]) -> float:
        """ Tính overlap score giữa 2 list (order-aware). """
        if not list_a or not list_b:
            return 0.0
        
        set_a = set(list_a)
        set_b = set(list_b)
        intersection = set_a & set_b    # type chung
        
        if not intersection:
            return 0.0
        
        # Tỉ lệ trùng
        union = set_a | set_b
        return len(intersection) / len(union)
