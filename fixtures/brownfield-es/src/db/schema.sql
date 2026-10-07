CREATE TABLE corridas (
    id TEXT PRIMARY KEY,
    estado TEXT NOT NULL,
    aprobada_por TEXT,
    aprobada_en TIMESTAMP
);

CREATE TABLE movimientos (
    id INTEGER PRIMARY KEY,
    corrida_id TEXT NOT NULL REFERENCES corridas(id),
    monto NUMERIC NOT NULL,
    estado TEXT NOT NULL
);
