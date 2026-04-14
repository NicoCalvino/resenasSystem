' ================================================================
'   Informes de Resenas -- Lanzador
' ================================================================
Option Explicit

Dim fso, shell, appDir, pythonw, script, cmd

Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
script = appDir & "\gui.py"

' Detectar entorno Python disponible
If fso.FileExists(appDir & "\python-portable\pythonw.exe") Then
    pythonw = appDir & "\python-portable\pythonw.exe"
ElseIf fso.FileExists(appDir & "\venv\Scripts\pythonw.exe") Then
    pythonw = appDir & "\venv\Scripts\pythonw.exe"
Else
    MsgBox "No se encontro Python." & vbCrLf & vbCrLf & _
           "Ejecuta 'instalar.bat' primero.", _
           vbCritical, "Informes de Resenas"
    WScript.Quit 1
End If

If Not fso.FileExists(script) Then
    MsgBox "No se encontro gui.py." & vbCrLf & _
           "Asegurate de que todos los archivos esten en la misma carpeta.", _
           vbCritical, "Informes de Resenas"
    WScript.Quit 1
End If

shell.CurrentDirectory = appDir
cmd = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & script & Chr(34)
shell.Run cmd, 0, False
