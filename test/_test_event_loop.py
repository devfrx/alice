"""Quick diagnostic: check event loop type and subprocess support."""
import asyncio
import sys
import platform

print(f"Python: {sys.version}")
print(f"Platform: {platform.system()}")
print(f"Default loop policy: {asyncio.get_event_loop_policy().__class__.__name__}")

loop = asyncio.new_event_loop()
print(f"Loop class: {loop.__class__.__name__}")

async def test():
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-n", "1", "-w", "200", "127.0.0.1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        print(f"Subprocess OK: {len(stdout)} bytes")
    except NotImplementedError as e:
        print(f"NotImplementedError: repr={repr(e)}, str='{str(e)}'")
    except Exception as e:
        print(f"Other error: {type(e).__name__}: {e}")

loop.run_until_complete(test())
loop.close()

# Now test with SelectorEventLoop explicitly
print("\n--- Testing with WindowsSelectorEventLoopPolicy ---")
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
loop2 = asyncio.new_event_loop()
print(f"Loop class: {loop2.__class__.__name__}")

async def test2():
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-n", "1", "-w", "200", "127.0.0.1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        print(f"Subprocess OK: {len(stdout)} bytes")
    except NotImplementedError as e:
        print(f"NotImplementedError: repr={repr(e)}, str='{str(e)}'")
    except Exception as e:
        print(f"Other error: {type(e).__name__}: {e}")

loop2.run_until_complete(test2())
loop2.close()
