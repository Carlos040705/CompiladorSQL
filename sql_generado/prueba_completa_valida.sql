CREATE TABLE IF NOT EXISTS estudiante (
    matricula SERIAL PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL,
    correo VARCHAR(255) UNIQUE,
    biografia TEXT DEFAULT 'Sin biografia registrada',
    edad INTEGER NOT NULL DEFAULT 18,
    semestre INTEGER DEFAULT 1,
    promedio NUMERIC(4, 2) DEFAULT 0.0,
    saldo_adeudo NUMERIC(10, 2) DEFAULT -10.5,
    becado BOOLEAN DEFAULT FALSE,
    activo BOOLEAN DEFAULT TRUE,
    fecha_ingreso VARCHAR(255) DEFAULT '2026-08-15'
);

CREATE TABLE IF NOT EXISTS curso (
    id_curso SERIAL PRIMARY KEY,
    id_estudiante INTEGER NOT NULL REFERENCES estudiante(matricula),
    nombre_curso VARCHAR(255) NOT NULL UNIQUE,
    creditos INTEGER DEFAULT 6,
    activo BOOLEAN DEFAULT TRUE
);

INSERT INTO estudiante (nombre, correo, edad, promedio, saldo_adeudo, becado, fecha_ingreso) VALUES ('Jose Cruz Castillo', 'jose.cruz@unach.mx', 67, 9.5, -150.75, TRUE, '2026-01-10');

INSERT INTO estudiante (nombre, correo, edad, semestre, promedio, saldo_adeudo, becado) VALUES ('Bernardo Manuel Vargas', 'bernardo.vargas@unach.mx', 21, 6, 9.2, 0.0, TRUE);

INSERT INTO estudiante (nombre, correo, edad, semestre, promedio, becado) VALUES ('Carlos Daniel', NULL, 19, 3, 8.4, FALSE);

INSERT INTO curso (id_estudiante, nombre_curso, creditos, activo) VALUES (1, 'Compiladores', 8, TRUE);

SELECT * FROM estudiante WHERE nombre = 'Jose Cruz Castillo';

SELECT matricula, nombre, promedio FROM estudiante WHERE semestre >= 5 ORDER BY promedio ASC LIMIT 10 OFFSET 0;

SELECT nombre, edad FROM estudiante WHERE becado = TRUE ORDER BY edad DESC;

SELECT semestre FROM estudiante INNER JOIN curso ON estudiante.matricula = curso.id_estudiante GROUP BY semestre HAVING semestre > 3 ORDER BY semestre ASC;

UPDATE estudiante SET semestre = 6, promedio = 9.8 WHERE matricula = 2001;

DELETE FROM estudiante WHERE activo = FALSE;

SELECT COUNT(*) FROM estudiante;

SELECT SUM(saldo_adeudo) FROM estudiante;

SELECT AVG(promedio) FROM estudiante WHERE becado = TRUE;

SELECT MAX(edad) FROM estudiante;

SELECT MIN(edad) FROM estudiante;

SELECT * FROM estudiante WHERE saldo_adeudo <= -100.0;

SELECT * FROM estudiante WHERE saldo_adeudo = +50.0;

UPDATE estudiante SET saldo_adeudo = -10, semestre = +2;

SELECT * FROM estudiante WHERE matricula % 2 = 0;

SELECT * FROM estudiante WHERE (edad + 2) % 5 = 0;

SELECT * FROM estudiante WHERE promedio * 10 / 2 + 5 - 3 - 1 >= 80;

SELECT * FROM estudiante WHERE -saldo_adeudo * 2 > 100;

SELECT * FROM estudiante WHERE -(edad - 18) < 0;

SELECT * FROM estudiante WHERE edad > 18 AND edad < 30 AND semestre >= 2 AND semestre <= 8 AND correo IS NOT NULL AND becado = TRUE;

SELECT * FROM estudiante WHERE becado = TRUE OR promedio >= 9.0 AND semestre > 4;

SELECT * FROM estudiante WHERE NOT becado = FALSE;

SELECT * FROM estudiante WHERE NOT (edad > 18 AND activo = TRUE);

SELECT * FROM estudiante WHERE NOT NOT (promedio >= 8.5 OR semestre >= 6 AND saldo_adeudo = 0);

SELECT matricula, nombre, promedio FROM estudiante WHERE NOT ((edad + 4) % 2 != 0 OR saldo_adeudo < -500.0) AND (promedio * 10 >= 85 OR becado = TRUE) ORDER BY nombre ASC LIMIT 5;
