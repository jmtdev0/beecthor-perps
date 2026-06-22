# Beecthor Perps Playbook

Este documento es la referencia operativa del sistema. Su objetivo no es adivinar Bitcoin, sino convertir tesis publicas de Beecthor en setups medibles, auditables y rechazables.

El playbook es vivo. Hoy el setup principal es `short_resistance_bearish_regime` porque el regimen reciente ha sido bajista/correctivo. Si dentro de meses el mercado entra en una fase alcista clara, este documento debe revisarse antes de permitir nuevos tipos de entradas.

## Principios

- El sistema solo opera setups escritos aqui.
- La tesis viene de Beecthor; la ejecucion la filtran reglas deterministas.
- El LLM puede extraer, resumir y auditar tesis, pero no puede saltarse limites de riesgo.
- Si falta direccion, zona, invalidacion, objetivo o confirmacion, la decision correcta es `WAIT`.
- Shadow mode y testnet van antes que cualquier ejecucion real.
- Ningun setup justifica usar apalancamiento alto al inicio.

## Estados Del Sistema

`WAIT`: no hay setup valido o falta confirmacion.

`ARMED`: la tesis es valida y el precio se acerca a zona, pero aun no hay gatillo.

`TRADE_READY`: tesis, zona, confirmacion y riesgo cumplen reglas.

`IN_POSITION`: existe una posicion abierta y el sistema solo puede gestionar riesgo o cerrar.

`DISABLED`: kill-switch activo, perdida diaria excedida, datos stale, config insegura o mainnet no autorizada.

## Tesis Estructurada

Cada video debe acabar convertido en una ficha parecida a:

```json
{
  "macro_bias": "bearish",
  "preferred_setup": "short_resistance",
  "short_zones": [{"low": 78000, "high": 78500, "stop_loss": 79500, "targets": [75500, 73000]}],
  "long_zones": [],
  "invalidation": 82500,
  "confidence": 0.72,
  "valid_until": "next_video_or_48h"
}
```

Una tesis caduca cuando llega un video nuevo, se invalida el nivel macro, pasan 48 horas sin activacion, o el precio ya hizo el movimiento principal.

## Playbook Principal: `short_resistance_bearish_regime`

Uso previsto: vender rebotes a resistencia cuando Beecthor mantiene sesgo bajista o correctivo.

Condiciones minimas:

- `macro_bias = bearish` o `corrective_bearish`.
- Beecthor menciona explicitamente zona de venta, rechazo, resistencia, gap, Golden Pocket, Value Area High o zona de descarga.
- El precio entra en la zona definida.
- Hay rechazo o fallo visible: mecha superior, cierre bajo la zona, perdida de microsoporte, SFP o rechazo de liquidez.
- Stop logico por encima de la zona.
- Primer objetivo ofrece al menos `1.5R`; idealmente `2R`.
- No hay otra posicion abierta.

Reglas de entrada:

- Entrada preferida: tras rechazo confirmado, no en el primer toque ciego.
- Entrada alternativa: limit en zona solo en shadow/testnet hasta tener estadistica.
- Si el precio rompe y acepta por encima de la zona, el setup queda invalidado.

Gestion:

- Stop obligatorio en exchange.
- Primer take-profit entre `1R` y `2R` o en el primer iman de liquidez.
- Mover a break-even tras parcial si el movimiento confirma.
- Cierres siempre `reduceOnly` o equivalente cuando el broker lo soporte.

Ejemplos observados:

- 2026-04-12: short cerca de `73.3k-74.1k`, coherente con video que esperaba cortos en agotamiento.
- 2026-04-19: short desde zona `78k`, coherente con barrida de `78k-80k`.
- 2026-05-25 a 2026-05-27: shorts desde `77.8k-78k`, coherentes con resistencia `78k-78.5k` y objetivo `75.5k/74k/73k`.

## Playbook Secundario: `long_support_sweep_reclaim`

Uso previsto: largo tactico despues de barrida de soporte cuando Beecthor espera rebote correctivo.

Este setup es mas fragil que los shorts en resistencia. Debe usar menor tamano y pedir mas confirmacion.

Condiciones minimas:

- Beecthor menciona soporte concreto, barrida inferior, POC, Value Area Low, Golden Pocket o zona donde buscar largo tactico.
- El precio barre la zona y recupera.
- Hay cierre por encima de la zona perdida o estructura alcista pequena.
- Stop queda por debajo del minimo de barrida.
- El objetivo no es macroalcista: es rebote tactico hacia resistencia.

Reglas de entrada:

- Prohibido comprar solo porque el precio toca soporte.
- Requiere reclaim o senal clara de giro.
- Si el precio cae sin recuperacion, `WAIT`.

Gestion:

- Tamano menor que en shorts de resistencia.
- Parcial rapido.
- No convertir un largo tactico en tesis de mercado alcista.

Ejemplos observados:

- 2026-03-09 a 2026-03-10: largos desde `66k`, coherentes con tesis de Value Area Low y rebote hacia `75k-76k`.
- 2026-05-29: largo tactico cerca de `73k` solo seria replicable si hubo barrida y recuperacion.

## Playbook Futuro: `bull_market_pullback_long`

Estado actual: deshabilitado.

Este setup solo se habilitara si el regimen cambia a alcista claro.

Condiciones para revisarlo:

- Beecthor deja de tratar las subidas como rebotes correctivos.
- Los videos empiezan a priorizar compras en retrocesos.
- BTC recupera estructuras macro relevantes.
- Los shorts en resistencia dejan de tener edge en shadow/testnet.

Posible forma futura:

- `macro_bias = bullish`.
- Comprar retrocesos a soporte, no perseguir rupturas extendidas.
- Stop bajo minimo de estructura.
- Objetivos por extensiones y liquidez superior.

Hasta que se revise formalmente, este playbook no puede operar.

## Reglas De No Trade

El sistema debe responder `WAIT` si:

- La tesis es ambigua.
- El video no da niveles claros.
- El precio esta en medio del rango.
- El movimiento ya ocurrio antes de la evaluacion.
- Hay noticia/evento extremo no contemplado.
- Los datos de mercado estan stale.
- El spread o liquidez son anormales.
- El stop necesario supera el limite de riesgo.
- Hay una posicion abierta.
- Se alcanzo la perdida diaria maxima.
- El LLM dice "no estoy seguro" o devuelve razonamiento contradictorio.

## Riesgo

Limites iniciales:

- Symbol allowlist in Demo: `BTCUSDC`, `BTCUSDT`.
- Modo: isolated.
- Max posiciones abiertas: `1`.
- Leverage inicial: hasta `5x` solo en Demo.
- Prohibido `10x/20x` en real hasta tener estadistica robusta.
- Stop obligatorio.
- Take-profit obligatorio.
- Max perdida diaria fija.
- Mainnet bloqueado hasta subcuenta, IP whitelist y confirmacion explicita.

Regla psicologica: una posicion que puede liquidar el capital de la subcuenta no es un trade, es un fallo de diseno.

## Papel Del LLM

Permitido:

- Extraer tesis del video.
- Convertir texto en JSON estructurado.
- Revisar si una senal respeta el playbook.
- Explicar post-trade si la operacion fue buena, mala o suerte.

Prohibido:

- Elegir apalancamiento fuera de limites.
- Aumentar tamano.
- Operar simbolos no permitidos.
- Saltarse stops.
- Convertir `WAIT` en `TRADE` por intuicion.
- Activar mainnet.

## Revision Periodica

Revisar este documento:

- Cada 2 semanas durante shadow/testnet.
- Cada vez que Beecthor cambie su sesgo macro.
- Cada vez que un playbook acumule 20 senales.
- Despues de una racha de 3 perdidas.
- Antes de pasar de testnet a real.

Cada revision debe responder:

- Que setup esta funcionando?
- Que setup esta perdiendo?
- Estamos entrando tarde?
- Los stops son razonables?
- El LLM esta aportando claridad o ruido?
- El regimen de mercado sigue siendo el mismo?

## Estado Actual

Activo:

- `short_resistance_bearish_regime`

Permitido solo con mucha confirmacion:

- `long_support_sweep_reclaim`

Deshabilitado:

- `bull_market_pullback_long`
- scalping sin tesis Beecthor
- trades por FOMO
- operar altcoins
- mainnet automatica
