# BLOCK/TOPOLOGY + PLACEMENT PIPELINE DESIGN (Implementation-ready)

**Last Updated:** 2026-02-26  
**Audience:** Backend AI team, Rule-engine team, EDA/KiCad integration team  
**Scope:** Schematic generation pipeline tối ưu đúng yêu cầu kỹ thuật + dễ nhìn, có tính đến khả năng triển khai PCB.

---

## 1) Mục tiêu hệ thống

Pipeline cần giải quyết đồng thời 3 mục tiêu:

1. **Đúng yêu cầu chức năng**: chọn đúng block/topology, template phù hợp intent.
2. **Dễ nhìn trên schematic**: layout sạch, ít giao dây, bố cục kỹ thuật chuẩn.
3. **Khả thi cho PCB**: netlist và cấu trúc placement thuận lợi cho đi dây thực tế.

Nguyên tắc vận hành:
- **ML đề xuất** (classification/ranking/placement).
- **Rule solver đảm bảo** (hard constraints + post-optimization).
- **Validator chặn lỗi kỹ thuật** trước khi xuất ra `.kicad_sch`.

---

## 2) Kiến trúc module tổng thể

```text
User Prompt
  -> Intent Extractor
  -> Topology Classifier + Template Ranker
  -> Topology Assembler (grammar-based extension)
  -> Placement Predictor (stage/order/orientation/spacing)
  -> Rule Solver (hard constraints + objective optimize)
  -> Circuit Validator (electrical + structural)
  -> Schematic Exporter (.kicad_sch)
  -> PCB Readiness Evaluator (proxy metrics)
```

### 2.1 Phân ranh trách nhiệm

- `ML Layer`: dự đoán nhanh và học từ dữ liệu.
- `Rule Layer`: ép chuẩn kỹ thuật và chuẩn hiển thị.
- `Application Layer`: điều phối pipeline, logging, retry/fallback.
- `Infra Layer`: lưu model, dataset, metrics, artifacts.

---

## 3) Cấu trúc code đề xuất (trực tiếp cho repo hiện tại)

```text
apps/api/app/
  application/circuits/
    use_cases/
      generate_from_prompt_v2.py
      rank_templates.py
      predict_block_placement.py
      solve_layout_rules.py
    dtos_ml.py
    ports_ml.py

  domains/circuits/
    placement/
      constraints.py
      objective.py
      solver.py
      symmetry.py
    ml/
      feature_extractors.py
      topology_labels.py
      placement_labels.py

  infrastructure/
    ml/
      model_registry.py
      inference_runner.py
      training_data_repo.py
    persistence/
      placement_metrics_repo.py

  interfaces/http/routes/
    circuits_ml.py

apps/api/scripts/ml/
  build_dataset.py
  train_topology_ranker.py
  train_placement_model.py
  evaluate_pipeline.py

artifacts/ml/
  datasets/
  models/
  reports/
```

---

## 4) Data schema

## 4.1 Nguồn dữ liệu đầu vào

- `resources/templates/*.json`
- `resources/templates_metadata/*.meta.json`
- `resources/block_library/block_library.json`
- `resources/block_library/grammar_rules.json`

## 4.2 Unified training record schema (`pipeline_record.v1`)

Mỗi record tương ứng 1 template hoặc 1 biến thể augment:

```json
{
  "record_id": "uuid",
  "template_id": "BJT-CE-04",
  "template_file": "bjt_ce_degen_unbypass_amplifier.json",
  "domain": {
    "category": "bjt",
    "family": "common_emitter",
    "tags": ["common_emitter", "unbypassed"]
  },
  "topology": {
    "block_sequence": ["ce_block"],
    "stage_count": 1,
    "graph_hash": "949b7c694b699f08"
  },
  "components": [
    {
      "id": "Q1",
      "type": "BJT",
      "group": "amplifier",
      "x": 0.0,
      "y": 0.0,
      "pins": ["C", "B", "E"],
      "params": {"beta": 100.0}
    }
  ],
  "nets": [
    {
      "id": "net_base",
      "connections": [["R1","2"],["Q1","B"],["CIN","1"]]
    }
  ],
  "labels": {
    "topology_class": "common_emitter_amplifier",
    "template_rank_target": 0.92,
    "placement": {
      "block_stage_index": {"stage1": 0},
      "orientation": {"stage1": "EAST"},
      "spacing": {"stage1_to_next_dx": 0.0, "stage1_to_next_dy": 0.0}
    }
  },
  "quality": {
    "crossings": 0,
    "wire_length": 132.5,
    "overlap_count": 0,
    "symmetry_error": 0.0
  },
  "split": "train"
}
```

## 4.3 Feature schema

### Topology/Ranking features
- Intent embedding (text)
- Capability vector (multi-hot)
- Block compatibility score features
- Template metadata stats: `stage_count`, `family`, `priority_score`
- Graph embedding của template (node/edge typed)

### Placement features
- Block graph adjacency matrix
- Port direction counts: input/output/power/ground
- Node attributes: type, group, degree, pin role
- Global context: single-ended/differential/push-pull

## 4.4 Label schema

- `topology_class`: single-label softmax
- `template_rank`: listwise/pairwise ranking target
- `stage_index`: ordinal label
- `orientation`: categorical (`EAST/WEST/NORTH/SOUTH`)
- `delta_position`: regression (`dx`, `dy`)

---

## 5) Data pipeline

## 5.1 Build dataset (`scripts/ml/build_dataset.py`)

Steps:
1. Load templates + metadata + grammar.
2. Normalize IDs, pin naming, group naming.
3. Build circuit graph (component node + net hyperedge -> bipartite transform).
4. Generate labels từ metadata `functional_structure.blocks`.
5. Compute quality baseline (wire length, crossings, overlap).
6. Augmentation:
   - parameter jitter (R/C/transistor model tương đương),
   - mirror/rotate layout hợp lệ,
   - stage permutation nếu grammar cho phép.
7. Export `parquet`:
   - `artifacts/ml/datasets/pipeline_record_v1_train.parquet`
   - `..._val.parquet`
   - `..._test.parquet`

## 5.2 Data quality gates

Fail record nếu:
- thiếu `template_id` hoặc `graph_hash`
- thiếu supply/ground port
- net có connection < 2
- block label không tồn tại trong `block_library`

---

## 6) Train loop

## 6.1 Topology classifier + template ranker

File: `scripts/ml/train_topology_ranker.py`

### Mô hình
- Shared encoder: MLP/GraphEncoder (GraphSAGE hoặc GAT nhỏ)
- Head A: `topology_class` (cross-entropy)
- Head B: `template_rank` (listwise softmax hoặc pairwise hinge)

### Loss

$$
\mathcal{L}_{topo}=\lambda_1\,\mathcal{L}_{ce}+\lambda_2\,\mathcal{L}_{rank}+\lambda_3\,\mathcal{L}_{capability\_coverage}
$$

### Pseudocode

```python
for epoch in range(max_epoch):
    for batch in train_loader:
        x_graph, x_text, y_topo, y_rank = batch
        h = encoder(x_graph, x_text)
        p_topo = topo_head(h)
        p_rank = rank_head(h)

        loss = l_ce(p_topo, y_topo) \
             + alpha * l_rank(p_rank, y_rank) \
             + beta * l_capability(p_topo, batch.required_capabilities)

        loss.backward()
        clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step(); optimizer.zero_grad()
```

### Output
- `artifacts/ml/models/topology_ranker_v1.pt`
- calibration metadata (`temperature`, class priors)

## 6.2 Placement model

File: `scripts/ml/train_placement_model.py`

### Mô hình
- Input: block graph + selected topology context
- Heads:
  - stage index (ordinal classification)
  - orientation (classification)
  - spacing `(dx, dy)` (regression)

### Loss

$$
\mathcal{L}_{place}=w_s\,\mathcal{L}_{stage}+w_o\,\mathcal{L}_{orient}+w_d\,\mathcal{L}_{delta}+w_r\,\mathcal{L}_{rule\_aware}
$$

`rule_aware`: phạt output vi phạm hướng input-left/output-right, symmetry hint.

### Training strategy
- Giai đoạn 1: teacher forcing theo ground-truth placement.
- Giai đoạn 2: scheduled sampling với solver-in-the-loop.
- Giai đoạn 3: fine-tune theo quality score hậu solver.

### Output
- `artifacts/ml/models/placement_predictor_v1.pt`

## 6.3 Mô hình đề xuất (từ baseline đến production)

Đề xuất huấn luyện theo 3 lớp mô hình để giảm rủi ro:

### A) Baseline cổ điển (triển khai nhanh, dễ giải thích)

1. **Decision Tree (Cây quyết định phân loại)**
  - Mục tiêu: phân loại nhanh `topology_class` theo feature thống kê.
  - Ưu điểm: dễ debug, giải thích bằng luật if-else.
  - Hạn chế: dễ overfit, tổng quát kém trên graph phức tạp.

2. **Random Forest / XGBoost (khuyến nghị baseline chính)**
  - Mục tiêu: xếp hạng template và dự đoán topology.
  - Feature input: capability vector, family/tag, stage_count, graph thống kê (node/edge degree histogram).
  - Ưu điểm: mạnh trên dữ liệu vừa/nhỏ, ít overfit hơn tree đơn.

### B) Mô hình neural cho production

3. **Topology Classifier + Ranker**
  - Phương án 1: Text MLP + GraphSAGE fusion.
  - Phương án 2: LightGAT fusion (khi dữ liệu tăng).
  - Output: `topology_class` + score ranking template.

4. **Placement Predictor**
  - Kiến trúc: Graph encoder + multi-head (stage/orientation/delta position).
  - Output: `stage_index`, `orientation`, `(dx, dy)` cho từng block.

### C) Chính sách chọn mô hình theo giai đoạn

- **Giai đoạn MVP**: Random Forest/XGBoost + Rule Solver.
- **Giai đoạn mở rộng**: thêm GNN classifier/ranker.
- **Giai đoạn tối ưu**: placement predictor học sâu + solver-in-the-loop.

## 6.4 Thông số mạng đề xuất (Input/Hidden/Output)

## 6.4.1 Topology classifier + template ranker

### Input
- `x_text`: embedding intent (kích thước 384 hoặc 768).
- `x_graph_node`: node features mỗi component (kích thước 32).
- `x_graph_edge`: edge/net features (kích thước 8).
- `x_meta`: metadata vector (`stage_count`, `family`, `priority_score`, capability multi-hot), kích thước 24-48.

### Hidden
- Graph encoder (GraphSAGE): 2-3 layers, hidden = 128.
- Text projector: 768 -> 256 (hoặc 384 -> 192).
- Fusion MLP: `[256 + 128 + 32] -> 256 -> 128`.

### Output
- Head A (classification): `output_dim = N_topology_classes` (softmax).
- Head B (ranking): `output_dim = N_templates` (listwise softmax) hoặc score scalar cho pairwise ranking.

### Hyperparameters khuyến nghị
- Batch size: 32.
- Learning rate: `1e-3` (AdamW).
- Weight decay: `1e-4`.
- Epoch: 80-120, early stopping patience 12.
- Dropout: 0.2.

## 6.4.2 Placement predictor

### Input
- Block graph tensor: `num_blocks x 48` features/block.
- Pairwise relation tensor: `num_blocks x num_blocks x 12`.
- Global context vector: 16 (single-ended/differential/push-pull + supply style).

### Hidden
- Graph encoder: 3 layers, hidden = 128.
- Relation encoder: MLP `12 -> 32 -> 32`.
- Shared trunk: `128 -> 128 -> 64`.

### Output
- Head 1 (stage index): ordinal logits, `output_dim = max_stage`.
- Head 2 (orientation): 4 lớp (`EAST/WEST/NORTH/SOUTH`).
- Head 3 (delta position): 2 số thực `(dx, dy)`.

### Hyperparameters khuyến nghị
- Batch size: 16.
- Learning rate: `5e-4`.
- Epoch: 100-150.
- Gradient clip: 1.0.
- Loss weights khởi tạo: `w_s=1.0, w_o=1.0, w_d=2.0, w_r=1.5`.

## 6.4.3 Baseline phi-neural để đối sánh

- Decision Tree:
  - `max_depth=6`, `min_samples_leaf=10`, `class_weight=balanced`.
- Random Forest:
  - `n_estimators=300`, `max_depth=12`, `min_samples_leaf=4`.
- XGBoost:
  - `n_estimators=500`, `max_depth=8`, `learning_rate=0.05`, `subsample=0.8`, `colsample_bytree=0.8`.

Luôn giữ baseline tree-based làm mốc để đánh giá mô hình neural có thực sự cải thiện hay không.

---

## 7) Inference API design

## 7.1 Endpoint đề xuất

### 1) Analyze + rank
`POST /api/circuits/ml/analyze-and-rank`

Request:
```json
{
  "prompt": "Create low-noise differential amplifier with output buffer",
  "constraints": {
    "supply": "single_supply_vref",
    "target_gain": 20,
    "prefer_symmetry": true
  },
  "top_k": 5
}
```

Response:
```json
{
  "intent": {"families": ["differential", "instrumentation"]},
  "topology_prediction": {"class": "instrumentation_amplifier", "confidence": 0.87},
  "template_candidates": [
    {"template_id": "OP-11", "score": 0.92},
    {"template_id": "OP-12", "score": 0.89}
  ]
}
```

### 2) Generate placed schematic
`POST /api/circuits/ml/generate-placed`

Request:
```json
{
  "prompt": "...",
  "chosen_template_id": "OP-11",
  "layout_policy": {
    "grid": 2.54,
    "strict_no_overlap": true,
    "minimize_crossing": true,
    "enforce_power_top_ground_bottom": true,
    "enforce_io_flow": true
  }
}
```

Response:
```json
{
  "circuit_id": "uuid",
  "topology": "instrumentation_with_output_buffer",
  "placement_quality": {
    "wire_length": 210.2,
    "crossings": 0,
    "overlap_count": 0,
    "symmetry_error": 0.03
  },
  "constraint_report": {
    "hard_constraints_passed": true,
    "violations": []
  },
  "export": {
    "kicad_sch_url": "/api/circuits/export/{id}/kicad/file.kicad_sch"
  }
}
```

## 7.2 Failure handling

- Nếu confidence thấp hoặc solver fail hard constraints:
  - fallback sang rule-only deterministic layout.
- Trả `fallback_used=true` trong response.

---

## 8) Rule solver (hậu xử lý bắt buộc)

File: `app/domains/circuits/placement/solver.py`

## 8.1 Hard constraints (must-pass)

1. Không chồng lấn bounding box.
2. Snap vào grid (`2.54mm` hoặc policy).
3. Nguồn trên / ground dưới.
4. Input trái / output phải.
5. Pin power pin phải nối đúng net domain.
6. Khoảng cách tối thiểu giữa block và wire label.

Nếu vi phạm hard constraints -> reject và retry (tối đa N lần) hoặc fallback deterministic.

## 8.2 Soft constraints (optimize)

- Ít giao dây.
- Wire length thấp.
- Canh hàng block cùng stage.
- Đối xứng cho vi sai/push-pull.
- Giữ khoảng trắng đọc tốt (readability spacing).

## 8.3 Objective function

$$
J = a\,L_{wire} + b\,P_{cross} + c\,P_{overlap} + d\,P_{misalign} + e\,P_{sym}
$$

Trong đó:
- $L_{wire}$: tổng Manhattan wire length.
- $P_{cross}$: số giao dây hoặc weighted crossing.
- $P_{overlap}$: diện tích/số overlap.
- $P_{misalign}$: sai lệch hàng/cột theo stage.
- $P_{sym}$: sai lệch qua trục đối xứng của cặp vi sai/push-pull.

Khuyến nghị trọng số khởi tạo:
- `a=1.0, b=8.0, c=100.0, d=2.0, e=3.0`

`P_overlap` được set rất lớn để gần như hard penalty.

## 8.4 Solver algorithm

- Input: layout từ ML + constraints.
- Bước 1: normalize & snap grid.
- Bước 2: feasibility repair (sửa overlap, IO flow, power/ground lanes).
- Bước 3: local search (simulated annealing hoặc hill-climbing có tabu ngắn).
- Bước 4: route proxy estimation và cập nhật score.
- Bước 5: xuất layout tốt nhất + constraint report.

---

## 9) Evaluator

File: `scripts/ml/evaluate_pipeline.py`

## 9.1 Metric cho phân loại/xếp hạng

- Topology accuracy
- F1 macro theo family
- Template Recall@K (K=1,3,5)
- NDCG@K cho ranking chất lượng cao

## 9.2 Metric cho placement schematic

- `crossings_per_circuit`
- `normalized_wire_length`
- `overlap_rate`
- `alignment_score`
- `symmetry_score`
- `hard_constraint_pass_rate`

## 9.3 Metric PCB-readiness (proxy)

- Estimated routability score
- Congestion heat (grid occupancy)
- Via estimate (proxy theo crossing + layer escape)
- Critical net length mismatch (đặc biệt vi sai)

## 9.4 Acceptance gate (release)

Một model/pipeline version được promote khi:
- `hard_constraint_pass_rate >= 99%`
- `crossings_per_circuit <= baseline * 0.7`
- `Template@3 >= 95%` cho bộ test chuẩn
- không tăng DRC-risk proxy so với baseline

---

## 10) Logging, observability, reproducibility

- Lưu per-run artifact:
  - selected topology/template
  - pre-solver layout
  - post-solver layout
  - objective breakdown (`wire, crossing, overlap, misalign, symmetry`)
  - fallback reason
- Định danh version:
  - `model_version`
  - `solver_policy_version`
  - `dataset_version`
- Gắn vào session hiện có (`artifacts/exports/sessions/{id}`)

## 10.1 Đề xuất PostgreSQL theo kiến trúc RAG (LLM + REGEX + RAG)

Mục tiêu: chuẩn hoá kho tri thức mạch để truy vấn lai theo thứ tự:
1. **REGEX/Rule hit** (chính xác cao cho pattern rõ ràng),
2. **RAG retrieval** (semantic search qua vector),
3. **LLM synthesis** (tổng hợp đáp án + chọn template).

## 10.1.1 Stack đề xuất

- PostgreSQL 16+
- Extension: `pgvector`, `pg_trgm`, `unaccent`
- Embedding model: 384 hoặc 768 dimensions (chọn 1 chuẩn và cố định)
- Retriever: hybrid `BM25-like (tsvector/trgm)` + vector similarity

## 10.1.2 Schema đề xuất

### Bảng tri thức chính

1. `knowledge_documents`
- `id` UUID PK
- `doc_type` (template|grammar|rule|manual|faq)
- `source_path` text
- `title` text
- `version` text
- `created_at`, `updated_at`

2. `knowledge_chunks`
- `id` UUID PK
- `document_id` UUID FK -> `knowledge_documents.id`
- `chunk_text` text
- `chunk_order` int
- `metadata` jsonb
- `tsv` tsvector

3. `knowledge_embeddings`
- `chunk_id` UUID PK FK -> `knowledge_chunks.id`
- `embedding` vector(768)  (hoặc vector(384), phải đồng nhất toàn hệ thống)
- `embedding_model` text

### Bảng phục vụ quyết định mạch

4. `template_catalog`
- `template_id` text PK
- `family` text
- `topology_class` text
- `capabilities` text[]
- `priority_score` float
- `template_json` jsonb

5. `block_library_catalog`
- `block_type` text PK
- `compatible_predecessors` text[]
- `compatible_successors` text[]
- `constraints` jsonb

6. `regex_rules`
- `id` UUID PK
- `rule_name` text
- `pattern` text
- `intent_key` text
- `priority` int
- `is_active` bool

7. `query_sessions`
- `id` UUID PK
- `user_query` text
- `regex_hits` jsonb
- `retrieved_chunks` jsonb
- `selected_templates` jsonb
- `final_answer` jsonb
- `created_at` timestamptz

## 10.1.3 Chỉ mục bắt buộc

- HNSW/IVFFlat cho `knowledge_embeddings.embedding`.
- GIN index cho `knowledge_chunks.tsv`.
- GIN/trgm cho `knowledge_chunks.chunk_text`.
- BTree cho `template_catalog.family`, `topology_class`.
- BTree cho `regex_rules.priority`, `is_active`.

## 10.1.4 Luồng truy vấn hybrid (runtime)

1. Tiền xử lý query: chuẩn hoá tiếng Việt, lower-case, bỏ dấu tuỳ policy.
2. Chạy `regex_rules` để bắt tín hiệu cứng (ví dụ: "vi sai", "push-pull", "class d").
3. Chạy retrieval:
   - lexical search từ `knowledge_chunks.tsv`
   - vector search từ `knowledge_embeddings.embedding`
4. Hợp nhất điểm: `score = 0.35*regex + 0.30*lexical + 0.35*vector`.
5. Lấy top-K chunks + top templates từ `template_catalog`.
6. LLM nhận context đã cắt gọn, xuất:
   - topology đề xuất,
   - template candidates,
   - lý do + ràng buộc kỹ thuật.
7. Rule solver xác nhận tính hợp lệ trước khi generate.

## 10.1.5 Chính sách fallback

- Nếu regex confidence cao: ưu tiên rule/template deterministic.
- Nếu RAG mismatch: trả về top-3 template kèm câu hỏi làm rõ.
- Nếu LLM fail/timeout: fallback sang regex + rule + ranker ML.

## 10.1.6 Đồng bộ dữ liệu RAG

- Job ETL định kỳ:
  - đọc `resources/templates`, `templates_metadata`, `block_library`, `grammar_rules`, docs domain,
  - chunk + embed + upsert vào PostgreSQL.
- Version hóa theo `knowledge_snapshot_id` để rollback dễ.

## 10.1.7 API đề xuất cho RAG service

- `POST /api/knowledge/reindex`
- `POST /api/knowledge/retrieve`
- `POST /api/circuits/assist-query` (LLM + REGEX + RAG orchestrator)
- `GET /api/knowledge/snapshots/{id}`

---

## 11) Kế hoạch triển khai theo sprint

## Sprint 1 (1-2 tuần)
- Dataset builder v1 + topology classifier/ranker baseline.
- API `analyze-and-rank`.
- Evaluator cho classification/ranking.

## Sprint 2 (1-2 tuần)
- Placement predictor v1.
- Rule solver v1 (hard constraints đầy đủ + objective cơ bản).
- API `generate-placed`.

## Sprint 3 (1-2 tuần)
- Solver-in-the-loop training.
- PCB-readiness evaluator proxy.
- A/B test so với deterministic layout hiện tại.

## Sprint 4 (1 tuần)
- Tinh chỉnh trọng số objective theo domain family.
- Chuẩn hoá report và rollout production guardrails.

---

## 12) Rủi ro và phương án giảm thiểu

1. **Dataset ít, dễ overfit**  
   -> Augmentation + multi-task + strong rule layer.

2. **ML output vi phạm kỹ thuật mạch**  
   -> hard constraints + validator bắt buộc + fallback deterministic.

3. **Tối ưu schematic làm xấu PCB**  
   -> thêm PCB proxy metrics trong objective/evaluator.

4. **Latency inference cao**  
   -> cache top templates theo intent + giới hạn local search iterations.

---

## 13) Definition of Done (DoD)

- Có pipeline chạy end-to-end từ prompt -> placed `.kicad_sch`.
- Có 2 model artifacts (`topology_ranker`, `placement_predictor`) versioned.
- Rule solver pass hard constraints >= 99% trên test set.
- Dashboard evaluator có đủ nhóm metric: intent/topology/ranking/placement/pcb-proxy.
- Có fallback deterministic ổn định cho mọi case confidence thấp hoặc solver fail.

---

## 14) Gợi ý triển khai đầu tiên (low-risk)

- Bắt đầu bằng **ranking + rule solver mạnh**, giữ placement model ở mức gợi ý stage/orientation.
- Chỉ nâng mức tự do của model khi evaluator cho thấy pass-rate ổn định.
- Duy trì nguyên tắc: **Model gợi ý, Rule đảm bảo** để đảm bảo mạch thực tế đẹp và ổn định.
