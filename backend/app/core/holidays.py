"""Colombian public holidays (Ley 51 de 1983, "Ley Emiliani"), loaded by hand.

Add the next year before it starts.
"""

from datetime import date

COLOMBIA_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2026
        date(2026, 1, 1),  # Año Nuevo
        date(2026, 1, 12),  # Reyes Magos
        date(2026, 3, 23),  # San José
        date(2026, 4, 2),  # Jueves Santo
        date(2026, 4, 3),  # Viernes Santo
        date(2026, 5, 1),  # Día del Trabajo
        date(2026, 5, 18),  # Ascensión del Señor
        date(2026, 6, 8),  # Corpus Christi
        date(2026, 6, 15),  # Sagrado Corazón
        date(2026, 6, 29),  # San Pedro y San Pablo
        date(2026, 7, 20),  # Independencia
        date(2026, 8, 7),  # Batalla de Boyacá
        date(2026, 8, 17),  # Asunción de la Virgen
        date(2026, 10, 12),  # Día de la Raza
        date(2026, 11, 2),  # Todos los Santos
        date(2026, 11, 16),  # Independencia de Cartagena
        date(2026, 12, 8),  # Inmaculada Concepción
        date(2026, 12, 25),  # Navidad
        # 2027
        date(2027, 1, 1),  # Año Nuevo
        date(2027, 1, 11),  # Reyes Magos
        date(2027, 3, 22),  # San José
        date(2027, 3, 25),  # Jueves Santo
        date(2027, 3, 26),  # Viernes Santo
        date(2027, 5, 1),  # Día del Trabajo
        date(2027, 5, 10),  # Ascensión del Señor
        date(2027, 5, 31),  # Corpus Christi
        date(2027, 6, 7),  # Sagrado Corazón
        date(2027, 7, 5),  # San Pedro y San Pablo
        date(2027, 7, 20),  # Independencia
        date(2027, 8, 7),  # Batalla de Boyacá
        date(2027, 8, 16),  # Asunción de la Virgen
        date(2027, 10, 18),  # Día de la Raza
        date(2027, 11, 1),  # Todos los Santos
        date(2027, 11, 15),  # Independencia de Cartagena
        date(2027, 12, 8),  # Inmaculada Concepción
        date(2027, 12, 25),  # Navidad
    }
)
