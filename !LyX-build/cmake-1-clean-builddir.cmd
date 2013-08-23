@ECHO OFF
FOR /F %%F IN ('DIR /B /AD      ^| FINDSTR /VIL "msvc2010-deps"'        ) DO RD  /Q /S  "%%F"
FOR /F %%F IN ('DIR /B /A-D /AH ^| FINDSTR /VILE ".gitignore .bat .cmd"') DO DEL /Q /AH "%%F"
FOR /F %%F IN ('DIR /B /A-D /AA ^| FINDSTR /VILE ".gitignore .bat .cmd"') DO DEL /Q /AA "%%F"
