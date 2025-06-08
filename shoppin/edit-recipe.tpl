<html>
<head>
    <meta http-equiv="refresh" content="1200">
<style>
p{
  width: 50%;
}

a:visited{
  color:blue;
}

a{
text-decoration: none
}

table, th, td {
  border: 1px dotted lightgray;
  border-collapse: collapse;
}
th, td {
  padding: 10px;
}
span.attribution{
  font-style: italic;
  font-size: 13px;
  color: gray;
}

.column {
  float: left;
  width: 50%;
}

.row:after {
  content: "";
  display: table;
  clear: both;
}

span.optional{
  color: gray;
}

a.x{
  opacity: 0.5;
  font-size: 0.8em;
  bottom: 0.3em;
  position: relative;
}

.greendot{
  opacity: 0.5;
  font-size: 0.8em;
}

.alreadyhave{
  text-align: center;
}

</style>
</head>
  <body>
    <h1><a href="/">&larr;</a> {{recipe.name}}</h1>

    <form action="/edit-recipe" method="POST">
    <label for="description"><h2>Description</h2></label>
    <textarea name="description" id="description" rows="4" cols="60">{{recipe.description}}</textarea>

    <label for="directions"><h2>Directions</h2></label>
    <textarea name="directions" id="directions" rows="10" cols="60">{{recipe.directions}}</textarea>

    <br><br><input type="submit" value="Save">
    </form>


  </body>
</html>
