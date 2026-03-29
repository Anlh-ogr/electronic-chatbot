import asyncio
from app.domains.circuits.ai_core.ai_core import AICore

async def main():
    ai_core = AICore()
    
    queries = [
        "thiết kế mạch BJT CE amplifier. tôi cần gain 350. Nguồn 24V",
    ]
    
    for query in queries:
        print(f"\n" + "="*50)
        print(f"Yêu cầu: {query}")
        print("="*50)
        
        result = ai_core.handle_request(user_text=query) 
        if asyncio.iscoroutine(result):
            result = await result
            
        print(f"Success: {result.success}")
        print(f"Stage Reached: {result.stage_reached}")
        if result.spec:
            print(f"Parsed Spec -> Loại mạch: {result.spec.circuit_type}, Gain: {result.spec.gain}")
        
        print("\n[Topology Plan Rationale]")
        if result.plan and result.plan.rationale:
            for r in result.plan.rationale:
                print(f" - {r}")
                
        if result.circuit:
            print(f"\n[Circuit Generate]")
            print(f"Loại thiết kế (Topology): {result.circuit.topology_type}")
            print(f"Gain công thức: {result.circuit.gain_formula}")
            print(f"Tham số đã tính (Solved params):")
            for k,v in result.circuit.solved_params.items():
                print(f"  {k} = {v}")
            
        if result.error:
            print(f"Error: {result.error}")

if __name__ == "__main__":
    asyncio.run(main())
