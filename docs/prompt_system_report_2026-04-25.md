# Bao cao he thong prompt trong Electronic Chatbot

Ngay cap nhat: 2026-04-25
Nguon du lieu: codebase hien tai tren nhanh main, test runtime noi bo, va tai lieu governance prompt.

## 1. Tong quan

He thong prompt hien tai da duoc chuan hoa theo huong contract-first va backend-first:
- Prompt khong truyen free-text ad-hoc cho cac callsite chinh.
- Payload gui LLM duoc dong goi theo req.v1.
- Output JSON duoc rang buoc schema typed (nlu.v1, domain.v1, cmp.v1).
- Co governance de kiem soat inventory, max_length va marker schema.

Muc tieu la tang do on dinh, giam loi parse output, va de quan tri prompt theo chuan thong nhat.

## 2. Pham vi bao cao

Bao cao tap trung vao:
- Cau truc payload prompt va response schema.
- Danh muc prompt dang su dung trong he thong.
- Vi tri callsite prompt trong code.
- Co che governance va ket qua test lien quan prompt/contract.
- Danh gia tien hoa tu mo hinh prompt cu sang mo hinh hien tai.

Khong bao gom benchmark do tre A/B toan he thong tren cung tap request production.

## 3. Kien truc prompt hien tai

### 3.1 Envelope req.v1

Payload LLM duoc dong goi theo cau truc:
- sv: phien ban payload, hien tai la req.v1
- tk: task id (vi du: nlu.extract.v1)
- in: input object theo task
- of: output format (json hoac md)

Callsite xay payload trung tam:
- apps/api/app/application/ai/llm_contracts.py:256

### 3.2 Response schema typed

He thong dung StrictSchemaModel voi extra=forbid de chan output du field:
- apps/api/app/application/ai/llm_contracts.py:9

Schema chinh:
- NLUIntentOutputV1 (nlu.v1): apps/api/app/application/ai/llm_contracts.py:96
- DomainCheckOutputV1 (domain.v1): apps/api/app/application/ai/llm_contracts.py:123
- ComponentProposalOutputV1 (cmp.v1): apps/api/app/application/ai/llm_contracts.py:128

### 3.3 Retry theo schema

Callsite JSON quan trong su dung max_schema_retries=2:
- NLU extract: apps/api/app/application/ai/nlu_service.py:953
- Domain check: apps/api/app/application/ai/chatbot_service.py:1552
- Component proposal orchestrator: apps/api/app/application/services/circuit_design_orchestrator.py:196

## 4. Danh muc prompt dang van hanh

Theo inventory:
- docs/prompts_inventory.md

Danh sach prompt_id va max_length:
- nlu.extract.v1: 1200
- cmp.propose.v1: 600
- domain.check.v1: 260
- chat.c.v1: 320
- chat.rf.v1: 520
- chat.rx.v1: 420
- nlg.s.v1: 1200
- nlg.e.v1: 360
- nlg.c.v1: 280
- nlg.m.v1: 320

Luu y:
- Inventory dang dinh nghia input_format cho tat ca prompt la req.v1 JSON: {sv, tk, in, of}.
- Output schema duoc khai bao ro (json typed hoac md text).

## 5. Prompt callsite map trong code

### 5.1 NLU va Domain gate

- nlu.extract.v1:
  - apps/api/app/application/ai/nlu_service.py:942
  - user_content=prompt_payload + response_model=NLUIntentOutputV1
- domain.check.v1:
  - apps/api/app/application/ai/chatbot_service.py:1539
  - response_model=DomainCheckOutputV1

### 5.2 Chat reasoning helpers

- chat.c.v1: apps/api/app/application/ai/chatbot_service.py:1577
- chat.rf.v1: apps/api/app/application/ai/chatbot_service.py:1610
- chat.rx.v1: apps/api/app/application/ai/chatbot_service.py:1656

### 5.3 NLG response generation

- nlg.s.v1: apps/api/app/application/ai/nlg_service.py:291
- nlg.e.v1: apps/api/app/application/ai/nlg_service.py:340
- nlg.c.v1: apps/api/app/application/ai/nlg_service.py:378
- nlg.m.v1: apps/api/app/application/ai/nlg_service.py:421

### 5.4 Circuit design orchestrator

- cmp.propose.v1: apps/api/app/application/services/circuit_design_orchestrator.py:244

## 6. Input boundaries lien quan prompt

Gioi han input nguoi dung (truoc khi vao prompt pipeline):
- Chat message max_length = 2000:
  - apps/api/app/interfaces/http/routes/chatbot.py:54
- Generate-from-prompt max 1000 ky tu:
  - apps/api/app/application/circuits/dtos.py:578

Dieu nay giup gioi han kich thuoc du lieu dau vao truoc khi build payload req.v1.

## 7. Governance va kha nang quan tri

### 7.1 Governance artifacts

- Prompt inventory: docs/prompts_inventory.md
- Governance report lich su migration: docs/prompt_input_pipeline_update_report_2026-04-19.md
- Governance checker script:
  - apps/api/scripts/prompt_governance_check.py

### 7.2 Ket qua governance runtime (2026-04-25)

Da chay:
- python scripts/prompt_governance_check.py

Ket qua:
- Prompt governance check passed

Y nghia:
- Prompt inventory hop le.
- Prompt max_length duoc kiem soat.
- Marker schema va cau truc governance duoc duy tri.

## 8. Ket qua test thuc te lien quan prompt

Da chay nhom test contract/payload:
- tests/domain/test_llm_json_payload_standardization.py
- tests/domain/test_nlu_intent_type_pipeline.py

Ket qua runtime:
- 14 passed, 1 warning, 0.91s

Noi dung duoc xac thuc tu test:
- user_content gui sang router la dict req.v1, khong phai string raw.
- task id dung theo tung callsite (nlu.extract.v1, domain.check.v1, chat.*, nlg.*).
- payload co sv=tk=in=of.
- nlu extract tuan thu schema nlu.v1 va loai bo output schema sai.

## 9. So sanh tien hoa: prompt cu vs prompt hien tai

### 9.1 Dac diem prompt cu (tham chieu commit de18363)

Callsite cu cho thay:
- user_content=user_text (truyen text truc tiep)
- chua bat buoc response_model typed ngay callsite chinh

Vi du tham chieu lich su:
- de18363: apps/api/app/application/ai/nlu_service.py, doan _call_llm_extraction

### 9.2 Dac diem prompt hien tai

- user_content=prompt_payload theo req.v1
- co response_model typed va max_schema_retries cho JSON tasks
- prompt inventory va governance policy ro rang
- co test regression cho payload chuan hoa

### 9.3 Danh gia tac dong

Diem manh:
- Tang do on dinh parse output
- Giam couplings voi prompt text dai
- De theo doi va quan tri thay doi prompt qua inventory
- De audit va test theo task id

Diem can tiep tuc:
- Chua co bao cao benchmark latency/chi phi token theo tung task id trong tai lieu hien tai
- Nen bo sung dashboard thong ke invalid-schema rate theo model/mode

## 10. Rui ro va khuyen nghi

### Rui ro hien tai

- Drift giua inventory va callsite co the xay ra neu doi prompt nhanh ma khong cap nhat inventory.
- Prompt md tasks (chat.*, nlg.*) khong co typed schema giong JSON tasks, can policy test output format chat che hon.
- Chua co gate bat buoc cho benchmark token va latency theo tung task.

### Khuyen nghi

1. Them CI check doi chieu task id thuc te trong code voi docs/prompts_inventory.md (khong chi check syntax).
2. Them metrics runtime cho moi task: prompt token, completion token, schema retry count, fail rate.
3. Bo sung smoke test bat buoc cho tat ca prompt_id trong inventory (it nhat 1 test/prompt).
4. Dinh ky review max_length theo du lieu production de toi uu chi phi va do on dinh.

## 11. Ket luan

He thong prompt hien tai da dat muc truong thanh tot ve kien truc va governance:
- Chuan hoa contract req.v1,
- Rang buoc schema typed cho JSON tasks,
- Co governance check,
- Co regression tests xac thuc payload.

So voi cach gui string prompt cu, phien ban hien tai de kiem soat hon, on dinh hon, va phu hop cho van hanh quy mo lon.
