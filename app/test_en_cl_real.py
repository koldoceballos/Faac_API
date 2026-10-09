# test_en_cl_real.py

from worker import call_en_cl

LICENCIA = "73693F9C"
PETICION = "30"

FICHERO_CLAVES = """
Licencia:73693F9C Peticion:30
-----------------------------------------------------------------------------------------
Boton 1
Trama original: A0A44DA05E5A7F55
Serial Fijo: A0
Serial: 42061 (Sume o reste varios numeros para no hacer un clon)
Personalizacion: 35860
Contador: 0 (Puede introducir otro valor si lo desea)
Semilla: E958CEDC
"""

resultado = call_en_cl(
    licencia=LICENCIA,
    peticion=PETICION,
    fichero_claves=FICHERO_CLAVES,
)

print("RESULTADO:", resultado)
