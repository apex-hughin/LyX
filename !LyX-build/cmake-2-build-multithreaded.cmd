@ECHO OFF

CMAKE --build . --clean-first --config MinSizeRel -- /m
IF %ERRORLEVEL% NEQ 0 GOTO BUILDERROR
GOTO END

:BUILDERROR
ECHO %~n0%~x0: build error: %ERRORLEVEL%
GOTO END

:END
PAUSE