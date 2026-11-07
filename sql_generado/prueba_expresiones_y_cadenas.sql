CREATE TABLE IF NOT EXISTS estudiante (
    matricula SERIAL PRIMARY KEY,
    nombre VARCHAR(255),
    edad INTEGER,
    semestre INTEGER,
    promedio NUMERIC(10, 2),
    saldo NUMERIC(10, 2),
    creditos INTEGER,
    activo BOOLEAN,
    becado BOOLEAN
);

CREATE TABLE IF NOT EXISTS curso (
    id_curso SERIAL PRIMARY KEY,
    nombre_curso VARCHAR(255),
    creditos INTEGER,
    activo BOOLEAN
);

UPDATE estudiante SET edad = 100 - 20 - 10;

UPDATE estudiante SET promedio = 10 + 20 * 3 / 2 - 15 % 4;

UPDATE estudiante SET saldo = -10;

UPDATE estudiante SET saldo = +25.5;

UPDATE estudiante SET saldo = -(-10 + 5) * -2;

SELECT * FROM estudiante WHERE -edad + 30 >= +10;

SELECT * FROM estudiante WHERE (edad + 2) * (semestre - 1) / (creditos % 3) >= 15;

SELECT * FROM estudiante WHERE NOT edad < 18;

SELECT * FROM estudiante WHERE NOT (edad > 18 AND activo = TRUE);

SELECT * FROM estudiante WHERE NOT (semestre = 1 OR semestre = 2) AND NOT becado = FALSE;

SELECT * FROM estudiante WHERE nombre = 'Jose';

SELECT nombre, edad FROM estudiante WHERE edad >= 18 ORDER BY edad ASC;

SELECT nombre, promedio FROM estudiante WHERE becado = TRUE ORDER BY promedio DESC LIMIT 5;

SELECT semestre, promedio FROM estudiante CROSS JOIN curso WHERE estudiante.activo = TRUE GROUP BY semestre, promedio HAVING promedio > 8.0;

SELECT matricula, nombre FROM estudiante CROSS JOIN curso WHERE NOT (estudiante.creditos < 4 OR estudiante.activo = FALSE) GROUP BY matricula, nombre, estudiante.creditos HAVING estudiante.creditos >= 6 ORDER BY nombre ASC LIMIT 20 OFFSET 5;
