"""LangGraph agents.

assistants.citizen_agent()   Nyaya Mitra - ReAct agent for citizens / paralegals (HITL clarifications)
assistants.staff_agent()     Registry Copilot - ReAct agent for court staff
document_analyst.graph()     OCR -> index -> map-reduce -> synthesize -> verify loop -> persist + handoff
undertrial_watch.graph()     proactive Sec. 479 BNSS scanner -> drafts -> human approval
registry.graph()             triage -> AI review -> schedule -> explain -> registrar approval -> publish
"""
