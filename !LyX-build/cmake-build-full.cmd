@ECHO OFF
CALL run_cmake.bat
IF %ERRORLEVEL% NEQ 0 GOTO CMAKEERROR

CMAKE --build . --clean-first --config MinSizeRel
IF %ERRORLEVEL% NEQ 0 GOTO BUILDERROR

CMAKE --build . --config MinSizeRel --target PACKAGE
IF %ERRORLEVEL% NEQ 0 GOTO PACKAGEERROR

CMAKE --build . --config MinSizeRel --target INSTALL
IF %ERRORLEVEL% NEQ 0 GOTO INSTALLERROR
GOTO END

:CMAKEERROR
ECHO %~n0%~x0: cmake error: %ERRORLEVEL%
GOTO END

:BUILDERROR
ECHO %~n0%~x0: build error: %ERRORLEVEL%
GOTO END

:PACKAGEERROR
ECHO %~n0%~x0: packaging error: %ERRORLEVEL%
GOTO END

:INSTALLERROR
ECHO %~n0%~x0: install error: %ERRORLEVEL%
GOTO END

:END
PAUSE