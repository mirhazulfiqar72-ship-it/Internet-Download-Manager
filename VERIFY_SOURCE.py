import compileall, sys
ok=compileall.compile_dir('.',quiet=1)
print('Python compile check:', 'PASS' if ok else 'FAIL')
if not ok: sys.exit(1)
