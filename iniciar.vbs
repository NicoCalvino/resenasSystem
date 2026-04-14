' ================================================================
'   Informes de Resenas -- Lanzador
'   Abre la interfaz grafica sin ventana de consola negra.
'   Doble clic para iniciar la aplicacion.
' ================================================================
Option Explicit

Dim fso, shell, appDir, pythonw, script

Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' Carpeta donde esta este archivo
appDir  = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = appDir & "\python-portable\pythonw.exe"
script  = appDir & "\gui.py"

' ── Verificaciones previas ────────────────────────────────────────
If Not fso.FileExists(pythonw) Then
    MsgBox "No se encontro el entorno de Python." & vbCrLf & vbCrLf & _
           "Solucion: ejecuta 'instalar.bat' para configurar la " & _
           "aplicacion antes de usarla.", _
           vbCritical, "Informes de Resenas"
    WScript.Quit 1
End If

If Not fso.FileExists(script) Then
    MsgBox "No se encontro el archivo principal de la aplicacion (gui.py)." & vbCrLf & vbCrLf & _
           "Asegurate de que todos los archivos de la app esten " & _
           "en la misma carpeta que este lanzador.", _
           vbCritical, "Informes de Resenas"
    WScript.Quit 1
End If

' ── Lanzar sin ventana de consola ────────────────────────────────
'  0 = ventana oculta   |   False = no esperar a que termine
shell.CurrentDirectory = appDir
shell.Run """" & pythonw & """ """ & script & """", 0, False
