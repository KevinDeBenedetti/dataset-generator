--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);

CREATE TABLE public.communes (
    code character varying(5) NOT NULL,
    nom text,
    population integer,
    surface numeric(10,2),
    maj date
);

ALTER TABLE public.communes OWNER TO admin;

CREATE TABLE public.regions (
    id integer NOT NULL,
    nom text
);

COPY public.communes (code, nom, population, surface, maj) FROM stdin;
29019	Brest	139456	49.51	2024-01-01
29232	Quimper	63283	84.45	\N
56121	Lorient; "port"	57149	17.48	2024-01-01
29103	C:\\dossier\ttab	12	1.00	2024-01-01
\.

INSERT INTO public.regions VALUES (53, 'Bretagne');
INSERT INTO public.regions VALUES (52, 'Pays de la Loire'), (28, 'Normandie');

ALTER TABLE ONLY public.communes
    ADD CONSTRAINT communes_pkey PRIMARY KEY (code);

CREATE INDEX communes_nom ON public.communes USING btree (nom);

GRANT SELECT ON TABLE public.communes TO lecteur;
