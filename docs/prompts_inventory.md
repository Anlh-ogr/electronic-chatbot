# Prompt Inventory

This inventory defines the governed prompt catalog for LLM communication.

| prompt_id | file | symbol | purpose | input_format | output_schema | max_length |
| --- | --- | --- | --- | --- | --- | --- |
| nlu.extract.v1 | apps/api/app/application/ai/nlu_service.py | NLUService._build_extraction_prompt | Extract normalized circuit intent from user text | req.v1 JSON: {sv,tk,in,of} | nlu.v1 | 1200 |
| cmp.propose.v1 | apps/api/app/application/services/circuit_design_orchestrator.py | CircuitDesignOrchestrator._build_system_prompt_for_components | Propose validated component set from intent+feedback | req.v1 JSON: {sv,tk,in,of} | cmp.v1 | 600 |
| domain.check.v1 | apps/api/app/application/ai/chatbot_service.py | ChatbotService._domain_check | Classify whether request is electronics-domain | req.v1 JSON: {sv,tk,in,of} | domain.v1 | 260 |
| chat.c.v1 | apps/api/app/application/ai/chatbot_service.py | ChatbotService._smart_clarification | Generate concise clarification question text | req.v1 JSON: {sv,tk,in,of} | md.v1 (text) | 320 |
| chat.rf.v1 | apps/api/app/application/ai/chatbot_service.py | ChatbotService._reasoning_fallback | Generate fallback design narrative when planner fails | req.v1 JSON: {sv,tk,in,of} | md.v1 (text) | 520 |
| chat.rx.v1 | apps/api/app/application/ai/chatbot_service.py | ChatbotService._reasoning_explain | Generate explanatory answer for existing circuit intent | req.v1 JSON: {sv,tk,in,of} | md.v1 (text) | 420 |
| nlg.s.v1 | apps/api/app/application/ai/nlg_service.py | NLGService._llm_success_response | Generate success response with engineering explanation | req.v1 JSON: {sv,tk,in,of} | md.v1 (text) | 1200 |
| nlg.e.v1 | apps/api/app/application/ai/nlg_service.py | NLGService._llm_error_response | Generate error response with remedies | req.v1 JSON: {sv,tk,in,of} | md.v1 (text) | 360 |
| nlg.c.v1 | apps/api/app/application/ai/nlg_service.py | NLGService._llm_clarification | Generate follow-up questions for missing data | req.v1 JSON: {sv,tk,in,of} | md.v1 (text) | 280 |
| nlg.m.v1 | apps/api/app/application/ai/nlg_service.py | NLGService._llm_modify_response | Summarize successful circuit edits | req.v1 JSON: {sv,tk,in,of} | md.v1 (text) | 320 |
