# Qué queda habilitado a concluir el lector de `failClosedEpisodes`

**Escrito:** 2026-09-02, después del sello y **antes** de abrir `recompute_claims` o
`Certificate.cs`. El compromiso y lo que yo sabía de antemano están en
`docs/prereg-episode-20260901.md`; el orden de los commits es la garantía.

**La pregunta que contesta este documento no es «cómo se computa el campo».** Las dos
implementaciones ya contestaron ésa, y coincidieron porque comparten el supuesto (§5.11). Ésta es:

> **Qué queda habilitado a concluir un lector de este campo, y qué tiene que ser verdad para que
> esa conclusión se sostenga.**

---

## 1. Quién lee esto, y qué decide

El certificado existe para **entregárselo a un tercero que va a actuar**: una firma que evalúa
darle capital a alguien, una contraparte, alguien decidiendo si confía. No lo lee el trader para
sí mismo — para eso no haría falta un documento verificable.

Ese lector llega a `failClosedEpisodes` buscando una sola cosa:

> **¿Este trader estuvo vigilado, y con cuánta continuidad?**

De ahí sale todo lo demás, y de ahí sale el error que el campo tiene que impedir.

## 2. LO PRIMERO, Y CASI TODO SE DERIVA DE ESTO

> **Un episodio de fail-closed es un hueco en el TESTIGO, no un hecho sobre el TRADER.**
>
> Su contenido entero es **una ausencia de observación**. No dice qué hizo la persona: dice que
> durante ese tramo **nadie estaba mirando**.

Un lector que llega desde «track record» va a leer una lista de episodios como una lista de
**incidentes del trader**. Es la lectura natural y es falsa. **Cada decisión de forma de este campo
se juzga por si empuja al lector hacia esa lectura o lo aleja de ella.**

## 3. Lo que el lector SÍ queda habilitado a concluir

### 3.1 «Durante este tramo, el guardián no estaba observando la cuenta»

**Qué tiene que ser verdad:** que el ledger registre la entrada y la salida de ese estado; que la
cadena verifique; que el rango declarado no excluya parte de la sesión; y que el reloj no haya
saltado dentro del tramo.

Si el reloj saltó, **la duración es ficción** y hay que decirlo ahí, no en otra sección que este
lector no va a cruzar.

### 3.2 «Fuera de esos tramos, el guardián estaba observando»

**Y esto es lo que el lector realmente quiere**, aunque la lista le hable de lo contrario.

**Qué tiene que ser verdad:** que el rango cubra **la sesión entera**, y que el registro esté
completo. Sobre un rango que corta antes, o sobre un archivo al que le falta la cola, el lector no
está mirando la vigilancia de una jornada: está mirando **una muestra presentada como un total**.

**Consecuencia de forma:** cuando el rango no cubre la sesión, o el registro está incompleto, la
lista de episodios **no puede presentarse como completa**. La afirmación fuerte que el lector saca
de ella —«el resto del día estuvo cubierto»— es la que deja de valer primero, y es la que nadie
escribe porque está implícita.

### 3.3 «Este tramo duró tanto»

**Qué tiene que ser verdad:** los dos extremos registrados, y el reloj monótono entre ellos.

**Y con una advertencia que va pegada al número, no en un apéndice:** un episodio que sigue abierto
al final del rango **no tiene duración conocida**, tiene una **cota inferior**. Publicar esa cota
como si fuera la duración es la clase de cifra que se escapa a un resumen.

## 4. Lo que el lector NO queda habilitado a concluir — y el campo tiene que impedirlo

### 4.1 «El trader hizo (o no hizo) X durante el episodio»

**El guardián no vio nada. Eso es lo que el episodio dice.** Cualquier cifra derivada de un tramo
ciego describe **lo que el testigo no pudo ver**, nunca lo que pasó.

**Y de acá sale la regla que gobierna todo el bloque:**

> **Una ausencia de observación no se publica como un cargo.**

Si una afirmación sobre el trader se vuelve peor porque hubo un episodio, esa afirmación está
usando la ceguera del testigo como si fuera evidencia sobre la persona. **Un tramo en que nadie
miró no puede empeorar el juicio sobre alguien.**

### 4.2 «El episodio fue causado por tal cosa»

**El lector va a buscar una causa, porque una lista de fallas sin causas se lee como negligencia.**
Y no la hay: lo único que el registro tiene es **qué pasó antes**, que no es lo mismo.

**Consecuencia de forma:** ningún campo de este bloque puede llamarse de manera que prometa una
causa. Si se publica el evento anterior —que es útil para reconstruir una línea de tiempo— **tiene
que llamarse por lo que es**, y el documento tiene que **decir en su cara que no establece causas**.
Una aclaración en otra sección no alcanza: compite con la lista y pierde.

### 4.3 «Alguien se enteró» / «alguien respondió»

**Nada en un episodio dice que una persona lo supo.** El registro es del guardián consigo mismo.

> **Un freno desoído es, en resultado, un freno que no disparó.** *(Sabía esto antes de escribir:
> ENMIENDA 2 del sello. No cuenta como hallazgo.)*

**Consecuencia de forma:** el campo **no debe sugerir** que el episodio fue atendido, y **la
categoría que lo mediría —un hecho sobre la interacción con una persona— es distinta de todo lo
demás de este bloque** y no puede mezclarse con ella. Un acuse humano dentro de la lista de
episodios sería leído como parte de la historia de la máquina.

### 4.4 «Cuántos episodios hubo mide la gravedad»

**Un conteo sin duraciones engaña en las dos direcciones**: diez tramos de dos segundos no son
peores que uno de una hora. Un lector ancla en el número entero.

### 4.5 «Cuánto duró mide la exposición»

**Y ésta es la que más importa y la que el campo hoy no puede sostener.** Lo que le importa al
lector no es cuánto duró la ceguera: es **qué había expuesto mientras duraba**. Una hora ciego con
la cuenta plana es una molestia; tres minutos ciego con una posición abierta y órdenes en el libro
es exactamente el riesgo que el guardián existe para quitar.

**Consecuencia de forma:** publicar duración **sin** el estado de la cuenta invita a la inferencia
equivocada, y el lector va a hacerla igual. Si el dato no se puede obtener —y hay motivos para que
no se pueda, porque el momento de la ceguera es justo cuando el broker no contesta— entonces **el
documento tiene que decir que la duración no mide exposición**, en vez de dejar que el número lo
sugiera solo.

### 4.6 «El episodio cerró, así que el guardián recuperó la vista»

Que se haya registrado el fin del estado dice **que el estado terminó**. No dice **por qué**:
puede haber vuelto la conexión, puede haber reiniciado el proceso, puede haberlo despejado una
persona. **Son tres historias distintas y el lector saca la más favorable.**

**Consecuencia de forma:** si el registro no distingue esas tres, el campo puede afirmar «el estado
terminó» y **no** «la vigilancia se restableció».

## 5. Lo que se sigue, en forma de campo

De 3 y 4, y **sólo** de 3 y 4:

| lo que el lector puede concluir | lo que el campo necesita |
|---|---|
| hubo un tramo sin observación | inicio y fin identificados en el registro, no interpretados |
| duró tanto | los dos extremos, y **si sigue abierto, decirlo como cota inferior y no como duración** |
| fuera de esos tramos hubo observación | que el bloque **declare si el rango cubre la sesión**, porque sin eso la conclusión no se sostiene |
| *(nada sobre el trader)* | que **ninguna afirmación sobre la persona empeore** por la existencia de un episodio |
| *(nada sobre la causa)* | que el campo del evento anterior **se llame por lo que es**, y que el documento **declare que no establece causas** |
| *(nada sobre si alguien se enteró)* | que los hechos sobre la interacción con una persona vivan **fuera** de este bloque |
| *(nada sobre exposición)* | que se declare que la duración **no** la mide, mientras el estado de la cuenta no esté |

**Y una que no es un campo sino una prohibición**, porque es la que un lector no puede detectar
solo:

> **Un episodio no puede ser insumo de ninguna afirmación adversa sobre el trader.** Si lo es, el
> documento está cobrándole a una persona el hecho de que su testigo se quedó ciego.

## 6. Lo que este documento NO es

No es una descripción de lo que las implementaciones hacen. **No las abrí para escribirlo**, y el
próximo paso —abrirlas y anotar cada desvío— es el que le da valor a éste.

**Cero desvíos sería la alarma, no la meta** (sello §3): significaría que lo escribí mirando el
código. Y de las cinco cosas que declaré saber de antemano, **ninguna cuenta como hallazgo** si
aparece acá.
