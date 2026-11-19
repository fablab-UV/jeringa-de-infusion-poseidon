# Jeringa de Infusión Poseidon — FabLab UV
### Adaptación de Hardware Abierto | Fablab UV 🚧 *En desarrollo*

Este repositorio contiene el material técnico para la construcción de una **bomba de jeringa (syringe pump) de código abierto**, basada en el sistema **Poseidon** desarrollado por el *Pachter Lab* ([Caltech](https://github.com/pachterlab/poseidon)). El proyecto busca entregar una alternativa de bajo costo a las bombas de infusión comerciales, fabricada con piezas impresas en 3D y componentes electrónicos de fácil adquisición.

> **Nota:** Este proyecto es una **adaptación del diseño original Poseidon**. Las diferencias principales respecto a la versión del Pachter Lab se detallan en la sección [*Diferencias respecto al diseño original*](#-diferencias-respecto-al-diseño-original).

---

# Objetivo del Proyecto

Desarrollar una bomba de jeringa funcional y de bajo costo capaz de:

1. **Control de flujo de precisión:** Desplazar el émbolo de una jeringa de forma controlada mediante un motor paso a paso y un husillo.
2. **Control desde computador:** Configurar velocidad y dirección de infusión/retiro mediante comunicación Serial (USB).
3. **Fabricación local:** Construir el sistema completo con las impresoras 3D y la electrónica disponible en el FabLab UV.

---

# Diferencias respecto al diseño original

Esta versión es una **adaptación simplificada** del [sistema Poseidon original](https://github.com/pachterlab/poseidon), pensada como primera iteración funcional:

| Característica | Poseidon original (Pachter Lab) | Adaptación FabLab UV |
| --- | --- | --- |
| Número de bombas | Hasta 3 bombas simultáneas | **1 bomba** |
| Driver de motor | CNC Shield + drivers DRV8825 | **1 driver A4988** (sin shield) |
| Microcontrolador | Arduino + CNC Shield | **Arduino UNO** con conexión directa al driver |
| Varillas guía | Diseño para **6 mm** | Modelo **redimensionado a 8 mm** |
| Protección del driver | Integrada en el shield | **Condensador electrolítico** añadido en la alimentación del motor (ver diagrama de conexiones) |

* La adaptación a **una sola bomba** responde a una primera etapa de validación; el diseño puede escalar a más canales en futuras iteraciones.
* El modelo 3D original fue diseñado para varillas de **6 mm**; en esta adaptación se **modificó el CAD para varillas de 8 mm**, ajustando soportes, carro y base.
* El **condensador** (100 µF electrolítico, ≥ 25 V recomendado) se conecta entre **VMOT y GND** del A4988 para proteger el driver de picos de voltaje generados por el motor.

---

# Requisitos del Sistema

## Hardware

* **Microcontrolador:** Arduino UNO
* **Driver de motor:** A4988 (1 unidad)
* **Motor:** Paso a paso NEMA 17 (200 pasos/rev)
* **Fuente de poder:** 12 V para alimentación del motor (VMOT)
* **Mecánica:** Husillo con tuerca, varillas guía de **8 mm**, rodamientos lineales LM8UU, acoplamiento flexible
* **Jeringa:** Estándar (BD 1 mL – 60 mL según aplicación)
* **Piezas impresas en 3D:** Base, carro (sled), soporte de motor y soporte de jeringa (archivos en `HARDWARE/`)
* **Condensador:** Electrolítico 100 µF (≥ 25 V)

## Software

* **Python:** 3.10+ (64-bit)
* **Arduino IDE:** 1.8+ o 2.x
* **Librería Arduino:** [AccelStepper](https://www.airspayce.com/mikem/arduino/AccelStepper/)
* **Sistema Operativo:** Windows 10/11 recomendado (compatible con Linux/Mac)

---

# Instalación del Entorno

## 1. Instalar Python 3.10+

Descargar desde:

https://www.python.org/downloads/

Durante la instalación marcar:

```text
☑ Add python.exe to PATH
```

---

## 2. Crear entorno virtual

Abrir PowerShell en la carpeta del proyecto:

```bash
py -3 -m venv .venv
```

---

## 3. Activar entorno virtual

### Windows PowerShell

```bash
.venv\Scripts\activate
```

Si el entorno se activó correctamente, la terminal mostrará:

```bash
(.venv)
```

---

# Instalación de Librerías

```bash
pip install pyserial PyQt5
```

**Nota:** En el Arduino IDE instalar la librería **AccelStepper** desde el Gestor de Librerías (*Sketch → Include Library → Manage Libraries*).

---

# Diagrama de Conexiones (Arduino UNO + A4988)

```text
Arduino UNO                     A4988                    Fuente 12 V
┌─────────────┐          ┌──────────────────┐          ┌──────────┐
│             │          │                  │          │          │
│  D2 (STEP) ─┼─────────►│ STEP             │          │          │
│  D3 (DIR)  ─┼─────────►│ DIR              │          │          │
│  D4 (EN)   ─┼─────────►│ ENABLE           │          │          │
│             │          │                  │          │          │
│  5V ────────┼─────────►│ VDD              │          │          │
│  GND ───────┼───┬─────►│ GND (lógica)     │          │          │
│             │   │      │                  │          │          │
│             │   │      │  VMOT ◄──────────┼──────────┤ +12V     │
│             │   │      │  GND  ◄────┬─────┼──────────┤ GND      │
│             │   │      │           │     │          │          │
│             │   │      │     [Condensador 100 µF]   │          │
│             │   │      │      VMOT (+) ── GND (−)   │          │
│             │   │      │                            │          │
│             │   │      │  1A, 1B, 2A, 2B ──► Motor NEMA 17      │
└─────────────┘   │      └──────────────────┘          └──────────┘
                  │
     GND común entre Arduino y fuente de 12 V

Nota: Conectar los pines RESET y SLEEP del A4988 entre sí (puente)
para habilitar el driver.
```

### Consideraciones importantes

* **El condensador de 100 µF es obligatorio** entre VMOT y GND (lo más cerca posible del driver): protege el A4988 de los picos de voltaje (*spikes*) del motor. Respetar la polaridad.
* **Nunca conectar o desconectar el motor con el driver energizado:** puede destruir el A4988.
* **Ajustar la corriente del driver** mediante el potenciómetro del A4988 antes de operar (limitar según la especificación del motor).
* Unir **todos los GND** (Arduino, driver y fuente de 12 V) en un punto común.
* Para suavizar el movimiento se puede configurar microstepping con los pines MS1, MS2, MS3 del A4988.

---

# Ejecución del Proyecto

## Paso 1 — Cargar el firmware en el Arduino

Abrir en el Arduino IDE:

```text
firmware/bomba_jeringa.ino
```

y cargarlo en el Arduino UNO.

## Paso 2 — Identificar el puerto COM

Verificar el puerto del Arduino (ej: `COM3` en Windows).

## Paso 3 — Ejecutar el control desde Python

```bash
python control_bomba.py
```

*(🚧 Interfaz en desarrollo — por ahora el control se realiza por comandos Serial)*

---

# Estructura del Repositorio

```text
jeringa-de-infusion-poseidon/
│
├── HARDWARE/                  # Piezas 3D adaptadas a varillas de 8 mm
│   ├── STL/
│   └── CAD/                   # Archivos editables (Fusion 360)
├── firmware/
│   └── bomba_jeringa.ino      # Control del A4988 con AccelStepper
├── software/
│   └── control_bomba.py       # Interfaz de control por Serial
├── docs/
│   └── BOM.md                 # Lista de materiales y costos
└── README.md
```

---

# Flujo del Sistema

```text
PC (Python + Serial USB) → Arduino UNO → Driver A4988 → Motor NEMA 17
                                                        │
                                              Husillo + tuerca
                                                        │
                                          Desplazamiento lineal del émbolo
                                                        │
                                              Jeringa (infusión/retiro)
```

1. El usuario define velocidad y dirección desde el computador.
2. Python envía los comandos por puerto Serial al Arduino.
3. El Arduino genera las señales STEP/DIR hacia el driver A4988.
4. El driver energiza las bobinas del motor paso a paso.
5. El motor gira el husillo, que traslada el carro sobre las varillas de 8 mm.
6. El carro empuja (o tira) del émbolo de la jeringa, controlando el flujo.

---

# Tecnologías Utilizadas

* Python + PySerial
* Arduino UNO + AccelStepper
* Driver A4988
* Motor paso a paso NEMA 17
* Impresión 3D FDM
* Diseño CAD (Fusion 360)
* Fabricación digital

---

# Aplicaciones Potenciales

* Microfluídica y laboratorios de investigación
* Dosificación controlada de líquidos
* Docencia en instrumentación biomédica
* Prototipado de equipamiento de laboratorio de bajo costo
* Automatización de experimentos

---

# Consideraciones de Seguridad

* Probar el sistema primero en **seco (dry lab)** antes de usarlo con líquidos.
* No usar con solventes orgánicos sin evaluar la compatibilidad con el plástico impreso (PLA/PETG).
* Ajustar el límite de corriente del A4988 para que el motor se detenga (*stall*) ante una obstrucción, evitando sobrepresión en la jeringa.
* Este dispositivo es un prototipo de investigación/docencia: **no es un dispositivo médico certificado**.

---

# Referencias

* **Repositorio original:** [pachterlab/poseidon](https://github.com/pachterlab/poseidon) — *poseidon system: open source syringe pumps and microscope for laboratories*
* **Documentación original:** https://pachterlab.github.io/poseidon/
* **Paper:** A. Sina Booeshaghi, Eduardo da Veiga Beltrame, Dylan Bannon, Jase Gehring and Lior Pachter, *"Principles of open source bioinstrumentation applied to the poseidon syringe pump system"*, **Scientific Reports 9**, Article 12385 (2019).
* **Diseño base de bomba:** Wijnen et al., *"Open-Source Syringe Pump Library"*, PLOS One (2014).

---

# Créditos

Adaptación desarrollada por **Maximiliano Gaete** y **Maria-Ignacia Rojas**,
estudiantes de pregrado de Ingeniería Civil Biomédica.

Proyecto desarrollado para el **Fablab de la Universidad de Valparaíso**
*Basado en el sistema Poseidon del Pachter Lab (Caltech)*
