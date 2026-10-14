
## 2026-08-12T18:20:04Z — Documents/Projects/Cristopher

- a app passou a ver 150 anúncios por site em vez de 25 — o OLX sozinho tem 738
- corrigi motas que apareciam com 5 mil km quando têm 25 mil (era o intervalo das revisões)
- corrigi motas dadas como pretas por terem símbolos ou farolins pretos
- peças e acessórios deixaram de aparecer na lista como se fossem a mota

---

## 2026-08-12T18:27:32Z — Documents/Projects/Cristopher

- todas as motas da lista passaram a ter a cor confirmada pela foto — as que não são pretas saíram
- anúncios cuja foto não carregava ficavam marcados como já vistos e nunca mais eram olhados

---

## 2026-08-13T14:54:47Z — Documents/Projects/Cristopher

- os cartões do Sono passaram a contar só as noites que o relógio mediu
- melhor e pior noite passaram a ser pela pontuação, não pelas horas
- no relógio, os números da bateria ficaram um por linha: carregou, gastou, a dormir, na sesta

---

## 2026-09-18T22:34:41Z — Documents/Projects/Cristopher

- corrigi o VS Code e o Sono no telemóvel: já não é preciso arrastar para o lado para ver tudo
- as notas e os TODOs voltaram a aparecer na app da NAS (os pedidos com o caminho do projecto estavam a ser recusados)

---

## 2026-09-18T23:19:26Z — Documents/Projects/Cristopher

- tirei o Planear Dia do menu
- no telemóvel as listas dos Reminders passaram a uma fila que rola, em vez de uma por linha a comer meio ecrã
- na secção VS Code a Nota deixou de ficar espremida em duas linhas e a barra dos projectos passou a duas linhas em vez de três
- a data do dashboard já não parte o ano para a linha de baixo
- desci um pouco o menu e o nome da secção, que ficavam colados às horas do iPhone

---

## 2026-09-19T11:59:05Z — Documents/Projects/Cristopher

- os TODOs de código no dashboard agora escondem-se com um clique e ficam assim da próxima vez
- tirei o plano de hoje do dashboard
- nos hábitos, os períodos e o botão de novo hábito ficam na mesma linha no telemóvel
- o Perguntar já não faz zoom no iPhone, e esse zoom deixou de passar para as outras secções

---

## 2026-09-27T17:58:03Z — Documents/Projects/Cristopher

- os Reminders do Cristopher passam para os da Apple quase na hora (menos de 1 segundo), com o Mac a fazer de ponte
- o Perguntar voltou a funcionar na NAS (dizia que a tabela de gastos não existia)
- os Deals voltaram a encontrar anúncios na NAS: o OLX bloqueava e o Vinted tinha mudado
- nova categoria Noite nos gastos, e regras por número de MB Way que se vêem e mudam em Gastos → Banco
- o jogo ao vivo do LoL deixou de trocar o mid com o adc; a barra lateral mostra tudo sem scroll

---

## 2026-09-27T18:13:24Z — Documents/Projects/Cristopher

- a barra lateral passou a duas colunas: todas as secções à vista, sem scroll e com botões do tamanho normal

---

## 2026-09-27T19:16:05Z — Documents/Projects/Cristopher

- mudar o nome de uma lista nos Reminders passa para os Reminders da Apple (e ao contrário)
- apagar uma lista no Cristopher apaga-a na Apple (antes voltava a aparecer)
- dá para arrastar um reminder para outra lista, com rato ou com toque longo no telemóvel
- no painel de um reminder há 'Mover para' para mudar de lista sem arrastar

---

## 2026-09-27T19:21:17Z — Documents/Projects/Cristopher

- o Screen Time abre na NAS com as horas medidas pelo Mac, em vez de pedir acesso a um ficheiro que lá não existe
- a média por dia do Screen Time conta só os dias com medição (dizia 3h14 ao lado de uma média de 8h51)

---

## 2026-09-28T10:11:51Z — Documents/Projects/Cristopher

- o ícone e a cor das listas dos Reminders passam a ser iguais no Cristopher e na Apple, nos dois sentidos
- dá para editar o texto dos TODOs na secção VS Code (carregar no texto ou no lápis)
- mudar a categoria de um gasto do banco já não muda os outros movimentos iguais, a não ser que marques a caixa

---

## 2026-09-28T13:43:21Z — Documents/Projects/Cristopher/backend

- a devolução da GoPro passa a anular a compra, e as Subscrições de Setembro deixam de contar 59,99€ a mais
- compras devolvidas pela Caixa com outro nome já se anulam sozinhas, e MB Way de pessoas diferentes deixam de se anular
- a página dos Reminders actualiza-se sozinha: o que escreves no iPhone aparece sem fazer refresh
- os emojis das listas passam a aparecer nos Lembretes da Apple em vez do ícone por omissão igual para todas

---

## 2026-09-29T18:10:34Z — Documents/Projects/Cristopher

- carregar no temporizador da sidebar abre uma nota da sessão, sem sair da página
- cada linha da nota fica com a hora a que a escrevi, e sobrevive a um F5
- ao parar, a nota fica guardada no bloco do calendário
- carregar num bloco com nota no calendário mostra a nota, com botão para editar o bloco

---

## 2026-09-29T18:44:19Z — Documents/Projects/Cristopher/frontend

- carregar no temporizador da barra lateral transforma o próprio bloco na nota da sessão
- Enter guarda a linha e volta ao temporizador; carregar outra vez no bloco ou Esc volta sem escrever
- tirei o painel da nota que abria ao lado do temporizador
- a etiqueta dos movimentos anulados nos Gastos passou de estorno para reembolsado

---

## 2026-10-01T19:17:38Z — Documents/Projects/Cristopher

- nos Gastos, ao abrir uma transação dá para marcar Pago com Klarna e escolher em quantas vezes (3 por omissão)
- a app mostra a prestação por mês e as datas das que ainda faltam
- a app reconhece na conta as prestações já cobradas, mesmo quando a Klarna cobra antes do dia, e deixa de as mandar guardar
- o valor a guardar para a Klarna aparece no cartão Restante e, mês a mês, na linha dos botões das Transações
- as transações pagas com Klarna ficam com etiqueta na lista

---

## 2026-10-05T19:13:41Z — Documents/Projects/Cristopher

- nas Transações dá para ver os gastos desde o dia em que o salário entrou, em vez do mês civil
- o dia do salário é lido da conta todos os meses e pode ser corrigido à mão
- os cartões do topo (gasto, restante, média por dia) passam a contar desde o salário nesse modo
- no editar gasto dá para criar categorias novas, com emoji, e apagá-las se estiverem vazias
- no dashboard o dia 😐 passou de «Mais ou menos» para «Normal»

---

## 2026-10-06T10:56:02Z — Documents/Projects/Cristopher

- o dinheiro que os amigos mandam pela conta do gás (ou outra) passa a descontar nessa conta em vez de contar como entrada
- a app sugere a ligação no editar da transação, com um ícone na lista nas transações com sugestão
- dá para marcar uma conta como paga por várias pessoas e ver quanto ainda falta receber

---

## 2026-10-06T11:25:32Z — Documents/Projects/Cristopher

- tirei a barra verde do salário por cima das transações
- o dia do salário corrige-se no lápis do cartão Salário, ou com «É o salário» ao abrir o movimento
- os botões das transações ficam todos numa linha a ocupar a largura toda
- no modo desde o salário, o Recebido já não conta o próprio salário

---

## 2026-10-06T15:19:59Z — Documents/Projects/Cristopher

- um dinheiro recebido pode descontar em várias contas ao mesmo tempo (ex.: dois levantamentos e um MB Way)
- nas contas divididas dá para dizer «a minha parte é X€» quando não é por igual
- o editar gasto ficou mais compacto e cabe no ecrã sem scroll, com as categorias a ocupar a largura toda
- tirei o «É o salário» do editar e encurtei a explicação da compra extraordinária

---

## 2026-10-06T15:51:05Z — Documents/Projects/Cristopher

- a app sugere descontar um MB Way em várias contas de uma vez (ex.: os 75€ do Rafael pelos dois levantamentos do chá)
- o reembolso reparte-se pelo que cada conta ainda tinha a receber, e cada uma mostra a parte certa
- o «Desde o salário» escolhido nas transações vale agora também no Resumo, nos cartões e nas outras abas

---

## 2026-10-06T16:32:11Z — Documents/Projects/Cristopher

- o Restante passou a contar devoluções de compras de outros períodos (faltavam 59,99€ da GoPro)
- confirmei as contas ao cêntimo contra o banco: Caixa e Revolut batem certo com a app

---

## 2026-10-11T16:13:14Z — Documents/Projects/Cristopher

- corrigi o cabeçalho do VS Code no iPad: a data ficava por cima do título e das abas
- os Gastos mostram por baixo do título o dinheiro no Revolut, na Caixa e o total
- adicionei 🌙 Saí / 🍺 Bebi no cartão do sono do Dashboard e em cada noite da página do Sono
- um gasto na Noite depois das 18h acende o Saí a verde para confirmar
- a Análise do Sono compara a noite depois de beber com as noites em casa

---

## 2026-10-11T16:13:34Z — Documents/Projects/Cristopher

- corrigi o cabeçalho do VS Code no iPad: a data ficava por cima do título e das abas
- os Gastos mostram por baixo do título o dinheiro no Revolut, na Caixa e o total
- adicionei 🌙 Saí / 🍺 Bebi no cartão do sono do Dashboard e em cada noite da página do Sono
- um gasto na Noite depois das 18h acende o Saí a verde para confirmar
- a Análise do Sono compara a noite depois de beber com as noites em casa

---

## 2026-10-12T14:26:36Z — Documents/Projects/Cristopher

- ao marcar Bebi aparece logo a escolha entre pouco, médio e muito, e o nível fica à vista no botão
- a lista das noites no Sono diz no ícone quanto se bebeu
- o hábito Gym marca-se sozinho quando o relógio grava um treino de ginásio, com a hora a que acabou
- desmarcar o gym à mão fica desmarcado — o relógio não o volta a marcar

---

## 2026-10-12T14:32:57Z — Documents/Projects/Cristopher

- o gym dos dias para trás também fica marcado: a app vai buscar ao relógio todos os treinos desde o primeiro dia
- a lista de treinos passa a ter os de antes de a app estar na NAS (faltava o de 9 de Setembro)

---

## 2026-10-13T00:27:32Z — Documents/Projects/Cristopher

- reescrevi o README: como correr, o que há em cada secção, configuração das integrações e deploy na NAS
- o exemplo das variáveis de ambiente passou a ter todas as opções, agrupadas e explicadas
- corrigi o exemplo que deixava o regresso do banco sem endereço quando copiado tal como estava
- pus o código todo no GitHub, sem chaves nem cópias do .env

---

## 2026-10-13T15:00:25Z — Documents/Projects/Cristopher

- corrigi o cronómetro do Flow que atrasava com o separador em segundo plano (1h aparecia como 19 min)
- o tempo passa a contar pelo relógio real, e acerta logo ao voltar à página

---

## 2026-10-13T15:19:02Z — Documents/Projects/Cristopher

- Hábitos: escolho ver por mês ou por ano e ando para trás para ver meses e anos anteriores
- tirei os Envelopes da semana e os Limites por categoria do Orçamento
- o Plano do Salário tem um botão para refazer os grupos com a média dos gastos dos últimos 3 meses, uma categoria por grupo
- cada grupo do plano pode ser editado em percentagem ou em euros por mês
- o Plano do Salário segue o Mês ou Desde o salário escolhido nas Transações

---

## 2026-10-13T15:35:35Z — Documents/Projects/Cristopher

- o Plano do Salário vem já definido a 100%: uma linha por categoria, 70% para gastar e 30% para investir
- os valores saem do que gastei de Abril a Setembro, sem as compras pontuais
- tirei o botão de recalcular pelos gastos

---

## 2026-10-13T16:54:19Z — Documents/Projects/Cristopher

- o Comprei da Wishlist já não cria um gasto: escolho a transação que já está na conta
- a lista de transações põe primeiro as que batem com o preço, contando as prestações da Klarna
- nos comprados aparece o que paguei de facto, e com Klarna o valor da prestação e quantas já foram
- compras antigas com o gasto duplicado avisam e deixam trocar pela transação verdadeira

---

## 2026-10-13T17:19:57Z — Documents/Projects/Cristopher

- o cronómetro do pomodoro passa a mostrar horas a partir de uma hora (1:35:11 em vez de 95:11)

---

## 2026-10-14T14:37:13Z — Documents/Projects/Cristopher

- verifiquei o histórico todo do git: a única chave exposta era a da Riot, e continua activa
- o endereço da NAS do Pedro deixou de aparecer nos ficheiros públicos do repositório
- cada commit passa a ser verificado e é recusado se levar uma chave ou password

---
